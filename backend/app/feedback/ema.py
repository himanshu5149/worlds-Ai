"""Feedback → routing-weight updates via exponential moving average (EMA).

Rules:
* small alpha (default 0.10) — no overreaction to single events
* early-sample dampening: effective alpha scales with samples/min_samples
* weights clamped to [min, max]
* fused answers update every constituent model
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.models import Feedback, Model, ModelResponse

logger = get_logger("prism.feedback")


@dataclass
class WeightUpdate:
    model_id: str
    old_weight: float
    new_weight: float
    effective_alpha: float


class EmaWeightUpdater:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def next_weight(self, *, rating: int, current: float, samples: int) -> tuple[float, float]:
        """Return (new_weight, effective_alpha)."""
        s = self.settings
        dampen = min(1.0, samples / max(1, s.feedback_min_samples))
        alpha = s.feedback_ema_alpha * dampen
        target = s.feedback_target_up if rating > 0 else s.feedback_target_down
        new = current * (1 - alpha) + target * alpha
        return max(s.feedback_weight_min, min(s.feedback_weight_max, new)), alpha


class FeedbackService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        updater: EmaWeightUpdater | None = None,
        settings: Settings | None = None,
    ):
        self.session_factory = session_factory
        self.updater = updater or EmaWeightUpdater(settings)
        self.settings = settings or get_settings()

    async def record_and_update(
        self, *, request_id, user_id, rating: int, comment: str | None = None
    ) -> list[WeightUpdate]:
        if rating not in (1, -1):
            raise ValueError("rating must be +1 or -1")
        async with self.session_factory() as session:
            session.add(
                Feedback(
                    request_id=request_id, user_id=user_id, rating=rating, comment=comment
                )
            )
            responses = (
                await session.scalars(
                    select(ModelResponse).where(
                        ModelResponse.request_id == request_id,
                        ModelResponse.selected.is_(True),
                    )
                )
            ).all()
            updates: list[WeightUpdate] = []
            for response in responses:
                updates.extend(await self._apply_to_model(session, response.model_id, rating))
            if not responses:
                logger.warning("feedback with no selected response", extra={"request_id": str(request_id)})
            await session.commit()
            return updates

    async def _apply_to_model(
        self, session: AsyncSession, model_id: str, rating: int
    ) -> list[WeightUpdate]:
        model = await session.get(Model, model_id)
        if model is None:
            return []
        meta = dict(model.meta or {})
        samples = int(meta.get("feedback_samples", 0))
        old_weight = model.routing_weight
        new_weight, alpha = self.updater.next_weight(
            rating=rating, current=old_weight, samples=samples
        )
        meta["feedback_samples"] = samples + 1
        model.meta = meta
        model.routing_weight = round(new_weight, 6)
        return [
            WeightUpdate(
                model_id=model_id,
                old_weight=old_weight,
                new_weight=model.routing_weight,
                effective_alpha=alpha,
            )
        ]

