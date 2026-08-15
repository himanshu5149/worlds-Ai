"""OpenAI official REST API (https://api.openai.com/v1)."""
from __future__ import annotations

import time

import httpx

from app.providers.base import (
    ErrorType,
    HealthResult,
    ModelStatus,
    ProviderAdapter,
    ProviderResponse,
    RateLimitInfo,
    StreamChunk,
)
from app.providers.http_common import iter_sse, raise_for_provider_error


class OpenAIAdapter(ProviderAdapter):
    name = "openai"
    default_base_url = "https://api.openai.com/v1"
    health_check_method = "free_endpoint"  # GET /models validates the key at zero cost
    verified_docs = "https://platform.openai.com/docs/api-reference"

    # ------------------------------------------------------------------ rate limits
    def parse_rate_limit_headers(self, headers: httpx.Headers) -> RateLimitInfo:
        def _int(key: str) -> int | None:
            value = headers.get(key)
            return int(value) if value is not None else None

        return RateLimitInfo(
            remaining=_int("x-ratelimit-remaining-requests"),
            limit=_int("x-ratelimit-limit-requests"),
            retry_after=self._extract_retry_after(headers),
        )

    # ------------------------------------------------------------------ errors
    def map_error(self, status_code: int, body: dict | None, headers: httpx.Headers) -> ErrorType:
        err = (body or {}).get("error") if isinstance(body, dict) else None
        code = (err or {}).get("code", "") if isinstance(err, dict) else ""
        if status_code == 401 or code in ("invalid_api_key", "insufficient_permissions_auth"):
            return ErrorType.AUTH_EXPIRED
        if status_code == 402:
            return ErrorType.PAID_REQUIRED
        if status_code == 429:
            if code == "insufficient_quota":
                return ErrorType.QUOTA_EXHAUSTED
            return ErrorType.RATE_LIMITED
        if status_code == 403:
            msg = str(err).lower()
            if "country" in msg or "region" in msg or "location" in msg:
                return ErrorType.REGION_BLOCKED
            return ErrorType.AUTH_EXPIRED
        if status_code == 400 and code == "content_policy_violation":
            return ErrorType.CONTENT_POLICY
        return super().map_error(status_code, body, headers)

    # ------------------------------------------------------------------ generate
    async def generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        started = time.monotonic()
        resp = await self._request(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            json={
                "model": model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "temperature": temperature,
                "max_tokens": self._clamp_tokens(max_tokens),
                "stream": False,
            },
            timeout=timeout,
        )
        await raise_for_provider_error(resp, self, self.name)
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        return ProviderResponse(
            text=(choice["message"].get("content") or ""),
            model=model,
            provider=self.name,
            latency_ms=(time.monotonic() - started) * 1000,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason"),
            rate_limit=self.parse_rate_limit_headers(resp.headers),
            cost_usd=self._estimate_openai_cost(model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
            raw=data,
        )

    # ------------------------------------------------------------------ stream
    async def stream_generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        async with self._client or httpx.AsyncClient() as client:
            req = client.build_request(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                json={
                    "model": model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "temperature": temperature,
                    "max_tokens": self._clamp_tokens(max_tokens),
                    "stream": True,
                    "stream_options": {"include_usage": True},
                },
                timeout=timeout or self.settings.provider_timeout_s,
            )
            resp = await client.send(req, stream=True)
            if resp.status_code >= 300:
                await raise_for_provider_error(resp, self, self.name)
            async for event in iter_sse(resp):
                choices = event.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        yield StreamChunk(text=piece)
                usage = event.get("usage")
                if usage:
                    yield StreamChunk(
                        text="",
                        usage={
                            "tokens_in": usage.get("prompt_tokens", 0),
                            "tokens_out": usage.get("completion_tokens", 0),
                        },
                        finish_reason=choices[0].get("finish_reason") if choices else None,
                    )

    # ------------------------------------------------------------------ health
    async def check_health(self) -> HealthResult:
        if not self.api_key:
            return HealthResult(
                ok=False, status=ModelStatus.AUTH_REQUIRED,
                error_type=ErrorType.AUTH_EXPIRED, message="no API key configured",
            )
        started = time.monotonic()
        try:
            resp = await self._request(
                "GET",
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10.0,
            )
        except Exception as exc:  # noqa: BLE001
            return HealthResult(
                ok=False, status=ModelStatus.DOWN, error_type=self.detect_error_type(exc),
                latency_ms=(time.monotonic() - started) * 1000, message=str(exc)[:200],
            )
        if resp.status_code == 200:
            return HealthResult(
                ok=True, status=ModelStatus.ACTIVE,
                latency_ms=(time.monotonic() - started) * 1000,
                quota_remaining=None,
            )
        return HealthResult(
            ok=False,
            status=ModelStatus.DOWN,
            error_type=self.map_error(resp.status_code, None, resp.headers),
            latency_ms=(time.monotonic() - started) * 1000,
            message=f"HTTP {resp.status_code}",
        )
