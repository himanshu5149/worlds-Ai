"""Mistral AI (official OpenAI-compatible endpoint: https://api.mistral.ai/v1)."""
from __future__ import annotations

from app.providers.openai import OpenAIAdapter


class MistralAdapter(OpenAIAdapter):
    """Mistral's official API is OpenAI-chat-completions compatible.

    https://docs.mistral.ai/api/#tag/chat — we reuse the OpenAI wire format and
    only override base URL and error nuances.
    """

    name = "mistral"
    default_base_url = "https://api.mistral.ai/v1"
    health_check_method = "passive"  # no free auth probe endpoint
    verified_docs = "https://docs.mistral.ai/api/"

    def map_error(self, status_code, body, headers):
        msg = str(body or {}).lower()
        if status_code == 403 and ("payment" in msg or "billing" in msg or "subscription" in msg):
            from app.providers.base import ErrorType

            return ErrorType.PAID_REQUIRED
        if status_code == 400 and "content" in msg and "moderated" in msg:
            from app.providers.base import ErrorType

            return ErrorType.CONTENT_POLICY
        return super().map_error(status_code, body, headers)

    def _estimate_openai_cost(self, model: str, tokens_in: int, tokens_out: int) -> float | None:
        # Mistral pricing varies by model; never guessed — leave to ops tooling.
        return None
