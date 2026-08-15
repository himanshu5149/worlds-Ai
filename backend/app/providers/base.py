"""Provider adapter contract.

Every connector implements the same surface so the orchestrator, health manager
and registry treat all providers uniformly:

* ``generate`` / ``stream_generate`` — official API calls only
* ``check_health`` — capability/auth/availability probe
* ``parse_rate_limit_headers`` — quota signals from response headers
* ``detect_error_type`` / ``map_error`` — typed failure classification

Only official REST endpoints / SDKs are used. No scraping, no unofficial
endpoints, no account rotation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import httpx

from app.core.config import Settings


class ErrorType(str, Enum):
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    PAID_REQUIRED = "PAID_REQUIRED"
    REGION_BLOCKED = "REGION_BLOCKED"
    TIMEOUT = "TIMEOUT"
    CONTENT_POLICY = "CONTENT_POLICY"
    PROVIDER_DOWN = "PROVIDER_DOWN"
    UNKNOWN = "UNKNOWN"


class ModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    COOLING = "COOLING"
    DOWN = "DOWN"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    PAID_REQUIRED = "PAID_REQUIRED"
    UNKNOWN = "UNKNOWN"


class ProviderError(Exception):
    def __init__(
        self,
        error_type: ErrorType,
        message: str,
        *,
        provider: str | None = None,
        retry_after: float | None = None,
        status_code: int | None = None,
    ):
        self.error_type = error_type
        self.provider = provider
        self.retry_after = retry_after
        self.status_code = status_code
        super().__init__(message)


@dataclass
class RateLimitInfo:
    remaining: int | None = None
    limit: int | None = None
    retry_after: float | None = None
    reset_at: datetime | None = None

    @property
    def near_exhausted(self) -> bool:
        """True when the provider signals the quota is almost empty."""
        if self.remaining is None or self.limit is None or self.limit <= 0:
            return self.retry_after is not None
        return self.remaining / self.limit <= 0.05


@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str


@dataclass
class ProviderResponse:
    text: str
    model: str
    provider: str
    latency_ms: float
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str | None = None
    rate_limit: RateLimitInfo | None = None
    cost_usd: float | None = None
    raw: dict[str, Any] | None = None


@dataclass
class StreamChunk:
    text: str
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


@dataclass
class HealthResult:
    ok: bool
    status: ModelStatus
    error_type: ErrorType | None = None
    latency_ms: float = 0.0
    quota_remaining: int | None = None
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(ABC):
    """Base class for all provider connectors."""

    name: str = "base"
    requires_verification: bool = False
    # free_endpoint -> auth probe at zero cost; passive -> no free probe exists,
    # health is inferred from live traffic; tiny_prompt -> paid micro-call (off by default)
    health_check_method: str = "passive"
    supports_streaming: bool = True
    credentials_required: bool = True
    default_base_url: str | None = None
    # Docs we verified the integration against (kept visible for audits).
    verified_docs: str = ""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ):
        from app.core.config import get_settings

        self.settings = settings or get_settings()
        self.api_key = api_key
        self.base_url = (base_url or self.default_base_url or "").rstrip("/")
        self._client = client

    # ------------------------------------------------------------- capabilities
    def capabilities(self) -> dict[str, Any]:
        return {
            "streaming": self.supports_streaming,
            "credentials_required": self.credentials_required,
            "requires_verification": self.requires_verification,
            "health_check_method": self.health_check_method,
            "verified_docs": self.verified_docs,
        }

    @property
    def has_credentials(self) -> bool:
        return not self.credentials_required or bool(self.api_key)

    # ------------------------------------------------------------- rate limits
    @abstractmethod
    def parse_rate_limit_headers(self, headers: httpx.Headers) -> RateLimitInfo: ...

    # ------------------------------------------------------------- error typing
    def detect_error_type(self, exc: BaseException) -> ErrorType:
        """Classify transport/HTTP exceptions."""
        if isinstance(exc, ProviderError):
            return exc.error_type
        if isinstance(exc, httpx.TimeoutException):
            return ErrorType.TIMEOUT
        if isinstance(exc, httpx.ConnectError):
            return ErrorType.PROVIDER_DOWN
        if isinstance(exc, httpx.HTTPStatusError):
            return self.map_error(exc.response.status_code, None, exc.response.headers)
        return ErrorType.UNKNOWN

    def map_error(self, status_code: int, body: dict | None, headers: httpx.Headers) -> ErrorType:
        """Generic official-HTTP mapping; adapters override for provider-specific bodies."""
        if status_code == 401:
            return ErrorType.AUTH_EXPIRED
        if status_code == 402:
            return ErrorType.PAID_REQUIRED
        if status_code == 403:
            return ErrorType.REGION_BLOCKED
        if status_code == 429:
            return ErrorType.RATE_LIMITED
        if 500 <= status_code < 600:
            return ErrorType.PROVIDER_DOWN
        return ErrorType.UNKNOWN

    # ------------------------------------------------------------- calls
    @abstractmethod
    async def generate(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.4,
        max_tokens: int = 1024,
        timeout: float | None = None,
    ) -> ProviderResponse: ...

    @abstractmethod
    async def stream_generate(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.4,
        max_tokens: int = 1024,
        timeout: float | None = None,
    ) -> AsyncIterator[StreamChunk]: ...

    @abstractmethod
    async def check_health(self) -> HealthResult: ...

    # ------------------------------------------------------------- helpers
    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        from app.providers.http_common import shared_request

        return await shared_request(
            self._client,
            method,
            url,
            headers=headers,
            json=json,
            timeout=timeout or self.settings.provider_timeout_s,
            provider=self.name,
        )

    @staticmethod
    def _extract_retry_after(headers: httpx.Headers) -> float | None:
        value = headers.get("retry-after")
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            from email.utils import parsedate_to_datetime

            try:
                dt = parsedate_to_datetime(value)
                now = datetime.now(dt.tzinfo)
                return max(0.0, (dt - now).total_seconds())
            except (TypeError, ValueError):
                return None

    def _clamp_tokens(self, value: int) -> int:
        return max(1, min(value, 4096))

    def _estimate_openai_cost(
        self, model: str, tokens_in: int, tokens_out: int
    ) -> float | None:
        """Cost estimate table for well-known models; None when unknown.

        Prices change; this is an internal ops estimate, never shown to users.
        """
        per_mtok: dict[str, tuple[float, float]] = {
            "gpt-4o": (2.50, 10.00),
            "gpt-4o-mini": (0.15, 0.60),
            "gpt-4.1": (2.00, 8.00),
            "gpt-4.1-mini": (0.40, 1.60),
        }
        if model not in per_mtok:
            return None
        pin, pout = per_mtok[model]
        return (tokens_in / 1e6) * pin + (tokens_out / 1e6) * pout

    @staticmethod
    def _linear_latency_score(latency_ms: float, soft_s: float, hard_s: float) -> float:
        """Deterministic latency component used by the judge."""
        t = latency_ms / 1000.0
        if t <= soft_s * 0.4:
            return 1.0
        denom = hard_s - soft_s * 0.4
        if denom <= 0:
            return 0.0
        return max(0.0, min(1.0, (hard_s - t) / denom))
