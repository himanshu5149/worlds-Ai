"""DeepSeek (official OpenAI-compatible endpoint: https://api.deepseek.com).

Verified: POST /chat/completions with Bearer auth. DeepSeek returns HTTP 402
with an "Insufficient Balance" body when the account has no credits — mapped
to QUOTA_EXHAUSTED/PAID_REQUIRED instead of a generic error.
"""
from __future__ import annotations

from app.providers.base import ErrorType, HealthResult, ModelStatus
from app.providers.openai import OpenAIAdapter


class DeepSeekAdapter(OpenAIAdapter):
    name = "deepseek"
    default_base_url = "https://api.deepseek.com"
    health_check_method = "free_endpoint"  # GET /models is documented
    verified_docs = "https://api-docs.deepseek.com/"

    def map_error(self, status_code, body, headers):
        msg = str(body or {}).lower()
        if status_code == 402 or "insufficient balance" in msg or "insufficient_quota" in msg:
            return ErrorType.QUOTA_EXHAUSTED
        if status_code == 400 and ("content" in msg and ("policy" in msg or "sensitive" in msg)):
            return ErrorType.CONTENT_POLICY
        return super().map_error(status_code, body, headers)

    def _estimate_openai_cost(self, model: str, tokens_in: int, tokens_out: int) -> float | None:
        return None

    async def check_health(self) -> HealthResult:
        if not self.api_key:
            return HealthResult(
                ok=False, status=ModelStatus.AUTH_REQUIRED,
                error_type=ErrorType.AUTH_EXPIRED, message="no API key configured",
            )
        # GET /models validates the key without consuming generation quota.
        return await super().check_health()
