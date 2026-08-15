"""Config-driven stub connectors.

Per the project constraints: if a provider endpoint or API shape is not fully
verified, we do NOT invent it. Unverified providers are registered as stubs
with ``requires_verification=True``; they serve canned, clearly-marked mock
output ONLY when ``PRISM_ALLOW_MOCK_PROVIDERS=true`` (dev/demo), and refuse to
run otherwise. The registry excludes them from production eligibility.
"""
from __future__ import annotations

import time

import httpx

from app.providers.base import (
    ChatMessage,
    ErrorType,
    HealthResult,
    ModelStatus,
    ProviderAdapter,
    ProviderError,
    ProviderResponse,
    RateLimitInfo,
    StreamChunk,
)

_STOP = {
    "what", "which", "when", "where", "who", "whom", "whose", "why", "how", "this",
    "that", "these", "those", "with", "about", "your", "you", "are", "there",
    "their", "have", "does", "will", "would", "should", "could", "please", "tell",
}


class StubAdapter(ProviderAdapter):
    """Unverified/mock connector. Never used in production eligibility."""

    name = "stub"
    requires_verification = True
    health_check_method = "passive"
    credentials_required = False

    def __init__(self, *, provider_label: str = "stub", mock_answer: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.provider_label = provider_label
        self.mock_answer = mock_answer

    def _allowed(self) -> bool:
        if self.settings.allow_mock_providers:
            return True
        raise ProviderError(
            ErrorType.AUTH_EXPIRED,
            f"{self.provider_label}: connector requires verification; "
            "mock mode is disabled (set PRISM_ALLOW_MOCK_PROVIDERS=true only for local demos)",
            provider=self.provider_label,
        )

    def parse_rate_limit_headers(self, headers: httpx.Headers) -> RateLimitInfo:
        return RateLimitInfo()

    def map_error(self, status_code: int, body: dict | None, headers: httpx.Headers) -> ErrorType:
        return ErrorType.UNKNOWN

    def _canned(self, model: str, messages: list[ChatMessage]) -> str:
        import re

        question = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if self.mock_answer:
            return self.mock_answer
        topic_words = [
            t for t in re.findall(r"[a-z]{4,}", question.lower()) if t not in _STOP
        ][:4]
        topics = ", ".join(topic_words) or "your question"
        return (
            f"[MOCK:{self.provider_label}] Simulated answer from an unverified demo connector "
            f"(model '{model}'). Your question concerns {topics}. Here are the key facts: "
            f"1. The subject has a long and well-documented history with broad agreement among "
            f"authoritative sources. 2. The main details are stable over time and appear "
            f"consistently across standard references. 3. Specific figures and dates can be "
            f"confirmed in reference works. This text is placeholder demo output, not a real "
            f"model answer."
        )

    async def generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        self._allowed()
        started = time.monotonic()
        await _sleep(0.05)
        text = self._canned(model, messages)
        return ProviderResponse(
            text=text,
            model=model,
            provider=self.provider_label,
            latency_ms=(time.monotonic() - started) * 1000,
            tokens_in=0,
            tokens_out=0,
            finish_reason="stop",
        )

    async def stream_generate(self, *, model, messages, temperature=0.4, max_tokens=1024, timeout=None):
        self._allowed()
        for word in self._canned(model, messages).split(" "):
            yield StreamChunk(text=word + " ")
            await _sleep(0.01)
        yield StreamChunk(text="", finish_reason="stop")

    async def check_health(self) -> HealthResult:
        if not self.settings.allow_mock_providers:
            return HealthResult(
                ok=False, status=ModelStatus.AUTH_REQUIRED, error_type=ErrorType.AUTH_EXPIRED,
                message="stub connector disabled (requires verification)",
            )
        return HealthResult(ok=True, status=ModelStatus.ACTIVE, message="mock connector")


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
