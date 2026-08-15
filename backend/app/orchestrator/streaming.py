"""SSE streaming support.

Design decision (documented): the pipeline judges first, then streams the
winner's tokens through its official streaming endpoint. The first token
therefore lands after the soft timeout, not instantly — the price of hidden
identity + multi-model judging. Deployments that need instant first-token can
add a "provisional stream" mode later without changing this interface.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

from app.core.logging import get_logger

logger = get_logger("prism.streaming")


async def stream_outcome(orchestrator, outcome, user_id, conversation_id, history=None) -> AsyncIterator[str]:
    """Yield SSE frames for an already-computed outcome (sync path):
    the pipeline resolved a winner; here we re-generate the winner's tokens
    via ``stream_generate`` for a true streaming experience."""

    async def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

    if outcome.status != "completed" or outcome.answer is None:
        yield await sse(
            "error",
            {"error": outcome.error or "no_answer", "message": outcome.error_detail or "unavailable"},
        )
        return

    best = outcome.candidates[0]
    yield await sse("meta", {
        "request_id": str(outcome.request_id),
        "fused": outcome.fused,
        "from_cache": outcome.from_cache,
    })
    # Re-generate from the winning model's official streaming endpoint.
    adapter = await orchestrator.registry.get_adapter(best.candidate.provider, user_id)
    model = best.candidate.model_id.split("/", 1)[1]

    query_text = outcome.metadata.get("query_text", "") or outcome.candidates[0].candidate.text
    messages = orchestrator._build_messages(query_text, history, None)
    try:
        async for chunk in adapter.stream_generate(model=model, messages=messages):
            if chunk.text:
                yield await sse("token", {"text": chunk.text})
            if chunk.finish_reason:
                yield await sse("done", {"finish_reason": chunk.finish_reason})
    except Exception as exc:  # noqa: BLE001 — fall back to the judged (complete) answer
        logger.warning("streaming failed, sending stored answer", extra={"exc": str(exc)[:200]})
        yield await sse("token", {"text": outcome.answer})
        yield await sse("done", {"finish_reason": "fallback_stored_answer"})
