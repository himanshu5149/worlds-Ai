"""Anthropic Messages API (https://api.anthropic.com/v1/messages)."""
from __future__ import annotations

import time

import httpx

from app.providers.base import (
    ChatMessage,
    ErrorType,
    HealthResult,
    ModelStatus,
    ProviderAdapter,
    ProviderResponse,
    RateLimitInfo,
    StreamChunk,
)
from app.providers.http_common import iter_sse, raise_for_provider_error


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"
    default_base_url = "https://api.anthropic.com/v1"
    # Anthropic exposes no free auth-probe endpoint; health is passive
    # (inferred from live traffic and recorded in health_events).
    health_check_method = "passive"
    verified_docs = "https://docs.anthropic.com/en/api/messages"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _split_messages(
        self, messages: list[ChatMessage]
    ) -> tuple[str | None, list[dict[str, str]]]:
        system_parts = [m.content for m in messages if m.role == "system"]
        rest = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        return ("\n\n".join(system_parts) or None), rest

    # ------------------------------------------------------------------ rate limits
    def parse_rate_limit_headers(self, headers: httpx.Headers) -> RateLimitInfo:
        def _int(key: str) -> int | None:
            value = headers.get(key)
            return int(value) if value is not None else None

        return RateLimitInfo(
            remaining=_int("anthropic-ratelimit-requests-remaining"),
            limit=_int("anthropic-ratelimit-requests-limit"),
            retry_after=self._extract_retry_after(headers),
        )

    # ------------------------------------------------------------------ errors
    def map_error(self, status_code: int, body: dict | None, headers: httpx.Headers) -> ErrorType:
        err = (body or {}).get("error") if isinstance(body, dict) else None
        err_type = (err or {}).get("type", "") if isinstance(err, dict) else ""
        message = str((err or {}).get("message", "") if isinstance(err, dict) else "").lower()
        if status_code == 401:
            return ErrorType.AUTH_EXPIRED
        if status_code == 403:
            return ErrorType.REGION_BLOCKED
        if status_code == 429:
            if "credit balance is too low" in message or "payment" in message:
                return ErrorType.PAID_REQUIRED
            return ErrorType.RATE_LIMITED
        if status_code == 400 and "prompt was blocked" in message:
            return ErrorType.CONTENT_POLICY
        if status_code == 529 or err_type == "overloaded_error":
            return ErrorType.PROVIDER_DOWN
        return super().map_error(status_code, body, headers)

    # ------------------------------------------------------------------ generate
    async def generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        started = time.monotonic()
        system, rest = self._split_messages(messages)
        payload: dict = {
            "model": model,
            "messages": rest,
            "max_tokens": self._clamp_tokens(max_tokens),
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        resp = await self._request(
            "POST", f"{self.base_url}/messages", headers=self._auth_headers(), json=payload,
            timeout=timeout,
        )
        await raise_for_provider_error(resp, self, self.name)
        data = resp.json()
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        usage = data.get("usage") or {}
        return ProviderResponse(
            text=text,
            model=model,
            provider=self.name,
            latency_ms=(time.monotonic() - started) * 1000,
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
            finish_reason=data.get("stop_reason"),
            rate_limit=self.parse_rate_limit_headers(resp.headers),
            raw=data,
        )

    # ------------------------------------------------------------------ stream
    async def stream_generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        system, rest = self._split_messages(messages)
        payload: dict = {
            "model": model,
            "messages": rest,
            "max_tokens": self._clamp_tokens(max_tokens),
            "temperature": temperature,
            "stream": True,
        }
        if system:
            payload["system"] = system
        req = self._client.build_request(
            "POST", f"{self.base_url}/messages", headers=self._auth_headers(), json=payload,
            timeout=timeout or self.settings.provider_timeout_s,
        ) if self._client else httpx.Request(
            "POST", f"{self.base_url}/messages", headers=self._auth_headers(), json=payload,
        )
        async with self._client or httpx.AsyncClient() as client:
            resp = await client.send(req, stream=True)
            if resp.status_code >= 300:
                await raise_for_provider_error(resp, self, self.name)
            async for event in iter_sse(resp):
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta") or {}
                    piece = delta.get("text")
                    if piece:
                        yield StreamChunk(text=piece)
                elif event.get("type") == "message_delta":
                    yield StreamChunk(
                        text="",
                        finish_reason=(event.get("delta") or {}).get("stop_reason"),
                        usage={"tokens_in": (event.get("usage") or {}).get("input_tokens", 0),
                               "tokens_out": (event.get("usage") or {}).get("output_tokens", 0)},
                    )

    # ------------------------------------------------------------------ health
    async def check_health(self) -> HealthResult:
        # Passive: presence of a key is required but true health is inferred
        # from traffic. Report ACTIVE-by-configuration; the health manager
        # downgrades on real failures.
        if not self.api_key:
            return HealthResult(
                ok=False, status=ModelStatus.AUTH_REQUIRED,
                error_type=ErrorType.AUTH_EXPIRED, message="no API key configured",
            )
        return HealthResult(
            ok=True, status=ModelStatus.ACTIVE,
            message="passive health check (no free auth probe exists)",
        )
