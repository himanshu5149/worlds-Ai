"""Prism AI API application factory."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import get_logger, new_request_id, setup_logging
from app.db.session import configure_db, dispose_db, get_session_factory, init_db
from app.embeddings.embedder import get_embedder
from app.health.manager import HealthManager
from app.observability.metrics import init_tracing, metrics_response
from app.orchestrator.fanout import FanoutOrchestrator
from app.providers.registry import ModelRegistry

logger = get_logger("prism.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, settings.pii_redact_logs)
    init_tracing(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        factory = configure_db(settings)
        if settings.is_dev:
            await init_db(settings)
        registry = ModelRegistry(factory, settings)
        await registry.seed_defaults()
        embedder = get_embedder(settings)
        health = HealthManager(registry, settings)
        orchestrator = FanoutOrchestrator(registry, embedder, settings, health=health)
        app.state.settings = settings
        app.state.registry = registry
        app.state.health = health
        app.state.orchestrator = orchestrator
        app.state.cache = orchestrator.cache
        app.state.embedder = embedder
        task = health.start() if settings.enable_background_tasks else None
        logger.info("prism api started", extra={"env": settings.env})
        yield
        if task is not None:
            await health.stop()
        await dispose_db()
        logger.info("prism api stopped")

    app = FastAPI(
        title="Prism AI",
        description=(
            "Multi-model fan-out gateway. Ask once; eligible models answer in "
            "parallel; the best answer is returned without revealing the model."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        rid = new_request_id()
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            duration = (time.monotonic() - started) * 1000
            logger.error(
                "request failed",
                extra={"method": request.method, "path": request.url.path, "ms": round(duration, 1)},
            )
            raise
        duration = (time.monotonic() - started) * 1000
        # Path only — query strings may carry sensitive data and are never logged.
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round(duration, 1),
            },
        )
        response.headers["X-Request-ID"] = rid
        return response

    register_exception_handlers(app)

    @app.get("/healthz", tags=["ops"])
    async def healthz():
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "service": "prism-api"}

    @app.get("/metrics", tags=["ops"])
    async def metrics():
        return metrics_response()

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
