"""xAI Grok (official OpenAI-compatible endpoint: https://api.x.ai/v1)."""
from __future__ import annotations

from app.providers.base import ErrorType
from app.providers.openai import OpenAIAdapter


class XAIAdapter(OpenAIAdapter):
    name = "xai"
    default_base_url = "https://api.x.ai/v1"
    health_check_method = "free_endpoint"  # GET /v1/models (OpenAI-compatible surface)
    verified_docs = "https://docs.x.ai/"

    def map_error(self, status_code, body, headers):
        msg = str(body or {}).lower()
        if status_code == 403 and "region" in msg:
            return ErrorType.REGION_BLOCKED
        return super().map_error(status_code, body, headers)

    def _estimate_openai_cost(self, model: str, tokens_in: int, tokens_out: int) -> float | None:
        return None
