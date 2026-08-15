"""Cohere official Chat API v2 (POST https://api.cohere.com/v2/chat).

Verified against https://docs.cohere.com/v2/reference/chat — messages are a
chronological list of {role, content}; response text lives in
``message.content[].text``.
"""
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


class CohereAdapter(ProviderAdapter):
    name = "cohere"
    default_base_url = "https://api.cohere.com/v2"
    health_check_method = "passive"
    verified_docs = "https://docs.cohere.com/v2/reference/chat"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    # ------------------------------------------------------------------ rate limits
    def parse_rate_limit_headers(self, headers: httpx.Headers) -> RateLimitInfo:
        # Cohere's v2 endpoints do not publish structured quota headers;
        # Retry-After on 429 is the reliable signal.
        return RateLimitInfo(retry_after=self._extract_retry_after(headers))

    # ------------------------------------------------------------------ errors
    def map_error(self, status_code: int, body: dict | None, headers: httpx.Headers) -> ErrorType:
        msg = str(body or {}).lower()
        if status_code == 401:
            return ErrorType.AUTH_EXPIRED
        if status_code == 403 and ("payment" in msg or "quota" in msg):
            return ErrorType.PAID_REQUIRED
        if status_code == 429:
            if "quota" in msg or "limit exceeded on trial" in msg:
                return ErrorType.QUOTA_EXHAUSTED
            return ErrorType.RATE_LIMITED
        if status_code == 400 and ("content moderation" in msg or "blocked" in msg):
            return ErrorType.CONTENT_POLICY
        return super().map_error(status_code, body, headers)

    # ------------------------------------------------------------------ generate
    async def generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        started = time.monotonic()
        resp = await self._request(
            "POST",
            f"{self.base_url}/chat",
            headers=self._headers(),
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
        message = data.get("message") or {}
        content = message.get("content") or []
        text = "".join(
            item.get("text", "") for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
        usage = data.get("usage") or {}
        tokens = usage.get("tokens") or {}
        return ProviderResponse(
            text=text,
            model=model,
            provider=self.name,
            latency_ms=(time.monotonic() - started) * 1000,
            tokens_in=tokens.get("input_tokens", 0),
            tokens_out=tokens.get("output_tokens", 0),
            finish_reason=data.get("finish_reason"),
            rate_limit=self.parse_rate_limit_headers(resp.headers),
            raw=data,
        )

    # ------------------------------------------------------------------ stream
    async def stream_generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        async with self._client or httpx.AsyncClient() as client:
            req = client.build_request(
                "POST",
                f"{self.base_url}/chat",
                headers=self._headers(),
                json={
                    "model": model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "temperature": temperature,
                    "max_tokens": self._clamp_tokens(max_tokens),
                    "stream": True,
                },
                timeout=timeout or self.settings.provider_timeout_s,
            )
            resp = await client.send(req, stream=True)
            if resp.status_code >= 300:
                await raise_for_provider_error(resp, self, self.name)
            async for event in iter_sse(resp):
                etype = event.get("type")
                if etype == "content-delta":
                    delta = event.get("delta") or {}
                    content = delta.get("message", {}).get("content", {})
                    piece = content.get("text") if isinstance(content, dict) else None
                    if piece:
                        yield StreamChunk(text=piece)
                elif etype == "message-end":
                    usage = (event.get("delta") or {}).get("usage") or {}
                    tokens = usage.get("tokens") or {}
                    yield StreamChunk(
                        text="",
                        finish_reason=(event.get("delta") or {}).get("finish_reason"),
                        usage={"tokens_in": tokens.get("input_tokens", 0),
                               "tokens_out": tokens.get("output_tokens", 0)},
                    )

    # ------------------------------------------------------------------ health
    async def check_health(self) -> HealthResult:
        if not self.api_key:
            return HealthResult(
                ok=False, status=ModelStatus.AUTH_REQUIRED,
                error_type=ErrorType.AUTH_EXPIRED, message="no API key configured",
            )
        return HealthResult(
            ok=True, status=ModelStatus.ACTIVE,
            message="passive health check (no free auth probe exists)",
        )
