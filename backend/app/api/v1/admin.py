"""Admin endpoints: model registry control, metrics, alerts, credentials."""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_health, get_registry
from app.core.errors import NotFoundError, ValidationFailed
from app.core.logging import get_logger
from app.core.security import encrypt_secret
from app.db.models import (
    AuditEvent,
    HealthEvent,
    ModelInvocation,
    ModelResponse,
    ProviderCredential,
    Request,
    User,
)
from app.db.session import get_session
from app.health.manager import HealthManager
from app.providers.base import ModelStatus
from app.providers.registry import ModelRegistry
from app.schemas.admin import (
    Alert,
    AlertsOut,
    CredentialIn,
    HealthCheckResult,
    HealthEventOut,
    MetricsOut,
    ModelHealthCard,
    ModelOut,
    ModelPatch,
)

logger = get_logger("prism.admin")
router = APIRouter(prefix="/admin", tags=["admin"])


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * p))
    return round(ordered[index], 1)


# ------------------------------------------------------------------ models
@router.get("/models", response_model=list[ModelOut])
async def list_models(
    admin: User = Depends(get_current_admin),
    registry: ModelRegistry = Depends(get_registry),
):
    models = await registry.list_models()
    adapters = await registry.adapter_states()
    out = []
    for m in models:
        caps = dict(m.capabilities or {})
        caps.update(adapters.get(m.provider, {}))
        out.append(
            ModelOut(
                id=m.id, provider=m.provider, tier=m.tier, routing_weight=m.routing_weight,
                context_window=m.context_window, status=m.status, capabilities=caps,
                requires_verification=m.requires_verification,
                credentials_required=m.credentials_required,
                last_health_check_at=m.last_health_check_at,
            )
        )
    return out


@router.patch("/models/{model_id}", response_model=ModelOut)
async def patch_model(
    model_id: str,
    body: ModelPatch,
    admin: User = Depends(get_current_admin),
    registry: ModelRegistry = Depends(get_registry),
    session: AsyncSession = Depends(get_session),
):
    model = await registry.get_model(model_id)
    if model is None:
        raise NotFoundError("Model not found.")
    if body.status is not None:
        model.status = body.status
        await registry.set_status(model_id, ModelStatus(body.status), message="manual override")
    if body.routing_weight is not None:
        model.routing_weight = body.routing_weight
    await session.commit()
    session.add(
        AuditEvent(user_id=admin.id, action="admin.model_update", resource_type="model",
                   resource_id=model_id, detail=body.model_dump(exclude_none=True))
    )
    await session.commit()
    refreshed = await registry.get_model(model_id)
    return ModelOut(
        id=refreshed.id, provider=refreshed.provider, tier=refreshed.tier,
        routing_weight=refreshed.routing_weight, context_window=refreshed.context_window,
        status=refreshed.status, capabilities=refreshed.capabilities or {},
        requires_verification=refreshed.requires_verification,
        credentials_required=refreshed.credentials_required,
        last_health_check_at=refreshed.last_health_check_at,
    )


@router.post("/models/{model_id}/health-check", response_model=HealthCheckResult)
async def health_check_model(
    model_id: str,
    admin: User = Depends(get_current_admin),
    registry: ModelRegistry = Depends(get_registry),
    health: HealthManager = Depends(get_health),
    session: AsyncSession = Depends(get_session),
):
    model = await registry.get_model(model_id)
    if model is None:
        raise NotFoundError("Model not found.")
    adapter = await registry.get_adapter(model.provider)
    started = time.monotonic()
    result = await adapter.check_health()
    latency = (time.monotonic() - started) * 1000
    if result.ok:
        state = health.state_for(model_id)
        state.consecutive_failures = 0
        await registry.set_status(model_id, ModelStatus.ACTIVE, message="manual health check")
    session.add(
        HealthEvent(
            model_id=model_id, status=result.status.value,
            error_type=result.error_type.value if result.error_type else None,
            latency_ms=latency, quota_remaining=result.quota_remaining, message=result.message,
        )
    )
    await session.commit()
    return HealthCheckResult(
        model_id=model_id, status=result.status.value,
        error_type=result.error_type.value if result.error_type else None,
        latency_ms=round(latency, 1), quota_remaining=result.quota_remaining,
        message=result.message,
    )


# ------------------------------------------------------------------ credentials
@router.post("/credentials", status_code=201)
async def add_credentials(
    body: CredentialIn,
    admin: User = Depends(get_current_admin),
    registry: ModelRegistry = Depends(get_registry),
    session: AsyncSession = Depends(get_session),
):
    known = {"openai", "anthropic", "gemini", "mistral", "cohere", "deepseek", "xai"}
    if body.provider not in known:
        raise ValidationFailed(f"Unknown provider '{body.provider}'. Known: {sorted(known)}")
    encrypted = encrypt_secret(body.api_key)
    session.add(
        ProviderCredential(
            provider=body.provider, owner_id=None, key_ref=encrypted, note=body.note
        )
    )
    session.add(
        AuditEvent(
            user_id=admin.id, action="admin.credential_add", resource_type="provider_credential",
            resource_id=body.provider,
        )
    )
    await session.commit()
    # Drop the cached adapter so the new key takes effect immediately.
    registry._adapters.pop(body.provider, None)
    return {"provider": body.provider, "stored": True, "encrypted": True}


# ------------------------------------------------------------------ metrics
@router.get("/metrics", response_model=MetricsOut)
async def metrics(
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
    registry: ModelRegistry = Depends(get_registry),
):
    # Bounded windows; computed python-side for portability.
    rows = (
        await session.execute(
            select(Request.created_at, Request.status, Request.cache_hit, Request.latency_ms)
            .order_by(Request.created_at.desc())
            .limit(2000)
        )
    ).all()
    total = len(rows)
    completed = sum(1 for r in rows if r.status in ("completed", "from_cache"))
    cache_hits = sum(1 for r in rows if r.cache_hit)
    latencies = [r.latency_ms for r in rows if r.latency_ms is not None]
    fused = (
        await session.scalar(
            select(func.count()).select_from(ModelResponse).where(ModelResponse.fused.is_(True))
        )
    ) or 0

    inv_rows = (
        await session.execute(
            select(ModelInvocation.model_id, ModelInvocation.status, ModelInvocation.latency_ms)
            .order_by(ModelInvocation.created_at.desc())
            .limit(5000)
        )
    ).all()
    by_model: dict[str, dict] = defaultdict(lambda: {"ok": 0, "err": 0, "lat": []})
    for model_id, status, latency in inv_rows:
        bucket = by_model[model_id]
        if status == "success":
            bucket["ok"] += 1
            if latency is not None:
                bucket["lat"].append(latency)
        else:
            bucket["err"] += 1

    models = await registry.list_models()
    cards = []
    for m in models:
        b = by_model.get(m.id, {"ok": 0, "err": 0, "lat": []})
        attempts = b["ok"] + b["err"]
        cards.append(
            ModelHealthCard(
                model_id=m.id, provider=m.provider, status=m.status,
                success_rate_24h=round(100 * b["ok"] / attempts, 1) if attempts else None,
                latency_p95_ms=_percentile(b["lat"], 0.95),
                invocations_24h=attempts,
            )
        )
    return MetricsOut(
        total_requests=total,
        success_rate=round(100 * completed / total, 1) if total else None,
        cache_hit_rate=round(100 * cache_hits / total, 1) if total else None,
        latency_p95_ms=_percentile(latencies, 0.95),
        fused_answers=fused,
        models=cards,
    )


@router.get("/alerts", response_model=AlertsOut)
async def alerts(
    admin: User = Depends(get_current_admin),
    registry: ModelRegistry = Depends(get_registry),
):
    alerts: list[Alert] = []
    for m in await registry.list_models():
        if m.status == "DOWN":
            alerts.append(Alert(severity="critical", model_id=m.id, message=f"{m.id} is DOWN."))
        elif m.status in ("PAID_REQUIRED",):
            alerts.append(Alert(severity="critical", model_id=m.id, message=f"{m.id} quota exhausted / payment required."))
        elif m.status == "AUTH_REQUIRED":
            alerts.append(Alert(severity="warning", model_id=m.id, message=f"{m.id} needs valid credentials."))
        elif m.status in ("DEGRADED", "COOLING"):
            alerts.append(Alert(severity="warning", model_id=m.id, message=f"{m.id} is {m.status.lower()}."))
    active = [m for m in await registry.list_models() if m.status == "ACTIVE"]
    if not active:
        alerts.append(Alert(severity="critical", message="No ACTIVE models — all chat requests will fall back."))
    return AlertsOut(alerts=alerts)


@router.get("/health-events", response_model=list[HealthEventOut])
async def health_events(
    model_id: str | None = None,
    limit: int = 50,
    admin: User = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(HealthEvent).order_by(HealthEvent.created_at.desc()).limit(min(limit, 500))
    if model_id:
        stmt = stmt.where(HealthEvent.model_id == model_id)
    rows = (await session.scalars(stmt)).all()
    return [
        HealthEventOut(
            model_id=e.model_id, status=e.status, error_type=e.error_type,
            latency_ms=e.latency_ms, quota_remaining=e.quota_remaining,
            message=e.message, created_at=e.created_at,
        )
        for e in rows
    ]
