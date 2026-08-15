"""Celery task for queued chat requests (fallback stage 5).

Enabled when PRISM_QUEUE_ENABLED=true and a Redis broker is reachable. The
worker re-runs the orchestrator with the stored request; the user polls
GET /api/v1/chat/requests/{id} for the eventual answer.
"""
from __future__ import annotations

import asyncio
import uuid

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("prism.queue")

_celery_app = None


def get_celery_app():
    global _celery_app
    if _celery_app is not None:
        return _celery_app
    try:
        from celery import Celery

        settings = get_settings()
        _celery_app = Celery(
            "prism", broker=settings.redis_url, backend=settings.redis_url
        )
        _celery_app.conf.task_routes = {"app.queue.tasks.*": {"queue": "chat"}}
        _celery_app.conf.task_acks_late = True
        _celery_app.conf.worker_prefetch_multiplier = 4
    except ImportError:
        logger.warning("celery not installed; queueing disabled")
        _celery_app = None
    return _celery_app


def enqueue_processing(request_id: uuid.UUID) -> None:
    app = get_celery_app()
    if app is None:
        return
    app.send_task(
        "app.queue.tasks.process_queued_request", args=[str(request_id)], queue="chat"
    )


async def _process(request_id: str) -> None:

    from app.db.models import Request
    from app.db.session import get_session_factory
    from app.embeddings.embedder import get_embedder
    from app.health.manager import HealthManager
    from app.orchestrator.fanout import FanoutOrchestrator
    from app.providers.registry import ModelRegistry

    settings = get_settings()
    factory = get_session_factory()
    registry = ModelRegistry(factory, settings)
    embedder = get_embedder(settings)
    health = HealthManager(registry, settings)
    orchestrator = FanoutOrchestrator(registry, embedder, settings, health=health)

    async with factory() as session:
        request = await session.get(Request, uuid.UUID(request_id))
        if request is None or request.status != "queued":
            return
        query_text = request.normalized_query
        user_id = request.user_id
        conversation_id = request.conversation_id

    outcome = await orchestrator.answer(
        user_id=user_id, conversation_id=conversation_id, query_text=query_text
    )
    async with factory() as session:
        request = await session.get(Request, uuid.UUID(request_id))
        if request is not None:
            request.status = outcome.status
            request.final_answer = outcome.answer
            request.latency_ms = int(outcome.latency_ms)
            request.error_type = outcome.error
            request.cache_hit = outcome.from_cache
            await session.commit()


def process_queued_request(request_id: str) -> None:
    asyncio.run(_process(request_id))
