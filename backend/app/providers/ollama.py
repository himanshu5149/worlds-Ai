"""Ollama local models (official /api/chat, no API key required).

Runs against any Ollama-compatible server (default http://localhost:11434).
This is the terminal fallback tier — fully local, no data leaves the host.
"""
from __future__ import annotations

import json
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
from app.providers.http_common import raise_for_provider_error


class OllamaAdapter(ProviderAdapter):
    name = "ollama"
    default_base_url = "http://localhost:11434"
    health_check_method = "free_endpoint"  # GET /api/tags
    credentials_required = False
    verified_docs = "https://github.com/ollama/ollama/blob/main/docs/api.md"

    # ------------------------------------------------------------------ rate limits
    def parse_rate_limit_headers(self, headers: httpx.Headers) -> RateLimitInfo:
        return RateLimitInfo()  # local server: no quota concept

    # ------------------------------------------------------------------ errors
    def map_error(self, status_code: int, body: dict | None, headers: httpx.Headers) -> ErrorType:
        if status_code == 404:
            return ErrorType.UNKNOWN  # usually "model not found" -> pull required
        return super().map_error(status_code, body, headers)

    # ------------------------------------------------------------------ generate
    async def generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        started = time.monotonic()
        resp = await self._request(
            "POST",
            f"{self.base_url}/api/chat",
            json={
                "model": model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": self._clamp_tokens(max_tokens),
                },
            },
            timeout=timeout,
        )
        await raise_for_provider_error(resp, self, self.name)
        data = resp.json()
        message = data.get("message") or {}
        return ProviderResponse(
            text=message.get("content", ""),
            model=model,
            provider=self.name,
            latency_ms=(time.monotonic() - started) * 1000,
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
            finish_reason=data.get("done_reason"),
            rate_limit=None,
            raw=data,
        )

    # ------------------------------------------------------------------ stream
    async def stream_generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        async with self._client or httpx.AsyncClient() as client:
            req = client.build_request(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "stream": True,
                    "options": {
                        "temperature": temperature,
                        "num_predict": self._clamp_tokens(max_tokens),
                    },
                },
                timeout=timeout or self.settings.provider_timeout_s,
            )
            resp = await client.send(req, stream=True)
            if resp.status_code >= 300:
                await raise_for_provider_error(resp, self, self.name)
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                piece = (event.get("message") or {}).get("content")
                if piece:
                    yield StreamChunk(text=piece)
                if event.get("done"):
                    yield StreamChunk(
                        text="",
                        finish_reason=event.get("done_reason"),
                        usage={"tokens_in": event.get("prompt_eval_count", 0),
                               "tokens_out": event.get("eval_count", 0)},
                    )

    # ------------------------------------------------------------------ health
    async def check_health(self) -> HealthResult:
        started = time.monotonic()
        try:
            resp = await self._request("GET", f"{self.base_url}/api/tags", timeout=10.0)
        except Exception as exc:  # noqa: BLE001
            return HealthResult(
                ok=False, status=ModelStatus.DOWN, error_type=self.detect_error_type(exc),
                latency_ms=(time.monotonic() - started) * 1000, message=str(exc)[:200],
            )
        if resp.status_code == 200:
            models = [m.get("name") for m in resp.json().get("models", [])]
            return HealthResult(
                ok=True, status=ModelStatus.ACTIVE,
                latency_ms=(time.monotonic() - started) * 1000,
                extra={"available_models": models},
            )
        return HealthResult(
            ok=False, status=ModelStatus.DOWN,
            error_type=self.map_error(resp.status_code, None, resp.headers),
            latency_ms=(time.monotonic() - started) * 1000, message=f"HTTP {resp.status_code}",
        )
