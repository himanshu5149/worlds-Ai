"""Fallback chain — the ordered degradation ladder.

Order (spec):
  1. remaining eligible official cloud models (primary/secondary tiers)
  2. models backed by user/admin-supplied official keys (same registry pool,
     resolved per-user; reached when the first-round pool was exhausted/failed)
  3. local / open-source models (Ollama-compatible)
  4. high-confidence semantic cache — ONLY with stricter guardrails
  5. queue the request (202) and process later
  6. clear failure message (503) — never fabricate an answer

Each stage activation is counted in Prometheus (prism_fallback_events_total).
"""
from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.db.models import Request
from app.orchestrator.normalize import NormalizedQuery

if TYPE_CHECKING:
    from app.orchestrator.fanout import FanoutOrchestrator, OrchestrationOutcome

logger = get_logger("prism.fallback")


class FallbackChain:
    def __init__(self, orchestrator: FanoutOrchestrator, settings):
        self.o = orchestrator
        self.settings = settings
        self.metrics = orchestrator.metrics

    async def resolve(
        self,
        *,
        user_id,
        conversation_id,
        normalized: NormalizedQuery,
        query_embedding,
        messages,
        tried: set[str],
        request_id: uuid.UUID,
        started: float,
        prior_failures: list[dict] | None = None,
    ) -> OrchestrationOutcome:
        failures = list(prior_failures or [])
        # Deep fallback stages may be invoked without the original message list;
        # rebuild from the normalized query so the local tier still receives the
        # user's question (history is dropped beyond this depth).
        if not messages:
            messages = self.o._build_messages(normalized.text, None, None)
        from app.orchestrator.fanout import OrchestrationOutcome

        def _fail(error: str, detail: str, status: str = "failed") -> OrchestrationOutcome:
            self.metrics.observe_chat(status, time.monotonic() - started)
            return OrchestrationOutcome(
                request_id=request_id,
                answer=None,
                status=status,
                failures=failures,
                latency_ms=(time.monotonic() - started) * 1000,
                error=error,
                error_detail=detail,
            )

        # ---- stage 1: remaining eligible cloud models ---------------------------
        # Re-read the live tried-set: previous stages may have extended it.
        tried = self.o._tried_by_request.get(request_id, tried)
        remaining = await self.o.registry.eligible(
            user_id=user_id,
            limit=self.settings.max_fanout_models,
            exclude=tried,
            tiers=("primary", "secondary"),
        )
        if remaining:
            self.metrics.fallback_events.labels(stage="cloud_round_2").inc()
            logger.info("fallback: cloud round 2", extra={"models": [m.model_id for m in remaining]})
            results = await self.o.fanout(normalized, remaining, messages, user_id, request_id=request_id)
            outcome = await self.o._judge_and_finalize(
                results, normalized, query_embedding, request_id, user_id,
                conversation_id, started,
            )
            if outcome.status == "completed" or outcome.status == "from_cache":
                return outcome
            failures.extend(outcome.failures)

        # ---- stage 2: user/admin-supplied keys ------------------------------------
        # Eligibility already resolves user-supplied credentials first; if the
        # user has none, we re-check the full pool for models the admin keyed.
        tried = self.o._tried_by_request.get(request_id, tried)
        user_key_models = await self.o.registry.eligible(
            user_id=user_id, limit=2, exclude=tried, tiers=("primary", "secondary", "stub")
        )
        if user_key_models:
            self.metrics.fallback_events.labels(stage="user_admin_keys").inc()
            results = await self.o.fanout(normalized, user_key_models, messages, user_id, request_id=request_id)
            outcome = await self.o._judge_and_finalize(
                results, normalized, query_embedding, request_id, user_id,
                conversation_id, started,
            )
            if outcome.status in ("completed", "from_cache"):
                return outcome
            failures.extend(outcome.failures)

        # ---- stage 3: local / open-source models (Ollama) --------------------------
        tried = self.o._tried_by_request.get(request_id, tried)
        local = await self.o.registry.eligible(
            user_id=user_id, limit=self.settings.max_fanout_models, exclude=tried, tiers=("local",)
        )
        if local:
            self.metrics.fallback_events.labels(stage="local_models").inc()
            logger.info("fallback: local models", extra={"models": [m.model_id for m in local]})
            results = await self.o.fanout(
                normalized, local, messages, user_id, request_id=request_id,
                hard_timeout=self.settings.fallback_timeout_s,
            )
            outcome = await self.o._judge_and_finalize(
                results, normalized, query_embedding, request_id, user_id,
                conversation_id, started,
            )
            if outcome.status in ("completed", "from_cache"):
                return outcome
            failures.extend(outcome.failures)

        # ---- stage 4: safe semantic cache (stricter thresholds) ---------------------
        hit = await self.o.cache.lookup(
            normalized, embedding=query_embedding, user_id=user_id, is_fallback=True
        )
        if hit is not None:
            self.metrics.fallback_events.labels(stage="safe_cache").inc()
            self.metrics.cache_hits.inc()
            await self.o._persist_request(
                request_id, user_id, conversation_id, normalized, status="from_cache",
                final_answer=hit.answer, cache_hit=True, latency_ms=0,
                metadata={"fallback": True, "cache_entry_id": hit.entry_id},
            )
            return OrchestrationOutcome(
                request_id=request_id,
                answer=hit.answer,
                status="from_cache",
                from_cache=True,
                failures=failures,
                latency_ms=(time.monotonic() - started) * 1000,
                cache_confidence=hit.confidence,
                metadata={"fallback_cache": True},
            )

        # ---- stage 5: queue (transparent status) --------------------------------------
        if self.settings.queue_enabled:
            position = await self._enqueue(
                request_id, user_id, conversation_id, normalized, messages
            )
            self.metrics.fallback_events.labels(stage="queue").inc()
            return OrchestrationOutcome(
                request_id=request_id,
                answer=None,
                status="queued",
                failures=failures,
                latency_ms=(time.monotonic() - started) * 1000,
                queue_position=position,
                message="All models are temporarily unavailable; your question has been queued.",
            )

        # ---- stage 6: clear failure — never fabricate -----------------------------------
        self.metrics.fallback_events.labels(stage="failure").inc()
        await self.o._persist_request(
            request_id, user_id, conversation_id, normalized, status="failed",
            latency_ms=int((time.monotonic() - started) * 1000),
            metadata={"failures": failures[:10]},
        )
        return _fail(
            "no_model_available",
            "All eligible models failed or are unavailable and no safe cached answer "
            "exists. Try again shortly or configure an official API key.",
        )

    async def _enqueue(
        self,
        request_id,
        user_id,
        conversation_id,
        normalized: NormalizedQuery,
        messages,
    ) -> int:
        """Persist the pending request; the Celery/ARQ worker picks it up."""
        async with self.o.registry.session_factory() as session:
            session.add(
                Request(
                    id=request_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    normalized_query=normalized.text,
                    query_hash=normalized.query_hash,
                    intent=normalized.intent,
                    language=normalized.language,
                    entities=normalized.entities,
                    time_sensitive=normalized.time_sensitive,
                    status="queued",
                    meta={"queue": True},
                )
            )
            await session.commit()
        try:
            from app.queue.tasks import enqueue_processing

            enqueue_processing(request_id)
        except Exception:
            logger.exception("failed to enqueue request")
        return 1
