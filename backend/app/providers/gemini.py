"""Google Gemini API (official REST: generativelanguage.googleapis.com)."""
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


class GeminiAdapter(ProviderAdapter):
    name = "gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
    health_check_method = "free_endpoint"  # GET /models lists available models (free)
    verified_docs = "https://ai.google.dev/api/generate-content"

    def _role_map(self, role: str) -> str:
        return "model" if role == "assistant" else "user"

    def _contents(self, messages: list[ChatMessage]) -> tuple[list[dict], str | None]:
        contents: list[dict] = []
        system_parts: list[str] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
                continue
            contents.append({"role": self._role_map(m.role), "parts": [{"text": m.content}]})
        return contents, ("\n\n".join(system_parts) or None)

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key or "", "content-type": "application/json"}

    # ------------------------------------------------------------------ rate limits
    def parse_rate_limit_headers(self, headers: httpx.Headers) -> RateLimitInfo:
        # Gemini does not expose structured quota headers on this endpoint;
        # Retry-After is the only reliable signal.
        return RateLimitInfo(retry_after=self._extract_retry_after(headers))

    # ------------------------------------------------------------------ errors
    def map_error(self, status_code: int, body: dict | None, headers: httpx.Headers) -> ErrorType:
        err = (body or {}).get("error") if isinstance(body, dict) else None
        reason = (err or {}).get("status", "").upper() if isinstance(err, dict) else ""
        msg = str((err or {}).get("message", "") if isinstance(err, dict) else "").lower()
        if status_code == 400 and "safety" in msg:
            return ErrorType.CONTENT_POLICY
        if status_code == 401 or reason in ("UNAUTHENTICATED", "API_KEY_INVALID"):
            return ErrorType.AUTH_EXPIRED
        if status_code == 403:
            if "location" in msg or "region" in msg or "country" in msg:
                return ErrorType.REGION_BLOCKED
            return ErrorType.AUTH_EXPIRED
        if status_code == 404 and "model" in msg:
            return ErrorType.UNKNOWN  # model id misconfigured
        if status_code == 429 or reason == "RESOURCE_EXHAUSTED":
            if "quota" in msg:
                return ErrorType.QUOTA_EXHAUSTED
            return ErrorType.RATE_LIMITED
        return super().map_error(status_code, body, headers)

    # ------------------------------------------------------------------ generate
    async def generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        started = time.monotonic()
        contents, system = self._contents(messages)
        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": self._clamp_tokens(max_tokens),
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        resp = await self._request(
            "POST",
            f"{self.base_url}/models/{model}:generateContent",
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        )
        await raise_for_provider_error(resp, self, self.name)
        data = resp.json()
        candidates = data.get("candidates") or []
        text = ""
        finish = None
        if candidates:
            first = candidates[0]
            text = "".join(
                (p or {}).get("text", "")
                for p in (first.get("content") or {}).get("parts", [])
                if isinstance(p, dict)
            )
            finish = first.get("finishReason")
        usage = data.get("usageMetadata") or {}
        return ProviderResponse(
            text=text,
            model=model,
            provider=self.name,
            latency_ms=(time.monotonic() - started) * 1000,
            tokens_in=usage.get("promptTokenCount", 0),
            tokens_out=usage.get("candidatesTokenCount", 0),
            finish_reason=finish,
            rate_limit=self.parse_rate_limit_headers(resp.headers),
            raw=data,
        )

    # ------------------------------------------------------------------ stream
    async def stream_generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        contents, system = self._contents(messages)
        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": self._clamp_tokens(max_tokens),
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        async with self._client or httpx.AsyncClient() as client:
            req = client.build_request(
                "POST",
                f"{self.base_url}/models/{model}:streamGenerateContent?alt=sse",
                headers=self._headers(),
                json=payload,
                timeout=timeout or self.settings.provider_timeout_s,
            )
            resp = await client.send(req, stream=True)
            if resp.status_code >= 300:
                await raise_for_provider_error(resp, self, self.name)
            async for event in iter_sse(resp):
                for candidate in event.get("candidates") or []:
                    for part in (candidate.get("content") or {}).get("parts", []):
                        piece = part.get("text")
                        if piece:
                            yield StreamChunk(text=piece)
                if event.get("usageMetadata"):
                    usage = event["usageMetadata"]
                    yield StreamChunk(
                        text="",
                        usage={"tokens_in": usage.get("promptTokenCount", 0),
                               "tokens_out": usage.get("candidatesTokenCount", 0)},
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
                "GET", f"{self.base_url}/models", headers=self._headers(), timeout=10.0
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
            )
        return HealthResult(
            ok=False, status=ModelStatus.DOWN,
            error_type=self.map_error(resp.status_code, None, resp.headers),
            latency_ms=(time.monotonic() - started) * 1000, message=f"HTTP {resp.status_code}",
        )
