"""Health & Availability Manager.

* periodic probe loop (default: every 30s) using each adapter's ``check_health``
* passive signals from live traffic (``on_invocation_result``) change state
  immediately — a 429 mid-request is not waited out until the next probe
* state machine: 2 consecutive failures -> DEGRADED, 5 -> DOWN; recovery needs
  N consecutive successes; AUTH/PAID states are sticky until credentials change
* exponential backoff with jitter; RATE_LIMITED -> COOLING until retry-after /
  backoff elapses
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.observability.metrics import Metrics, get_metrics
from app.providers.base import ErrorType, ModelStatus, RateLimitInfo
from app.providers.registry import ModelRegistry

logger = get_logger("prism.health")


@dataclass
class ModelHealthState:
    status: ModelStatus = ModelStatus.UNKNOWN
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    next_check_at: float = 0.0  # monotonic seconds
    backoff_s: float = 0.0

    def backoff_delay(self, settings: Settings) -> float:
        failures = max(1, self.consecutive_failures)
        base = settings.health_backoff_base_s
        cap = settings.health_backoff_max_s
        delay = min(base * (2 ** (failures - 1)), cap)
        return delay * random.uniform(0.75, 1.5)


class HealthManager:
    def __init__(
        self,
        registry: ModelRegistry,
        settings: Settings | None = None,
        metrics: Metrics | None = None,
    ):
        self.registry = registry
        self.settings = settings or get_settings()
        self.metrics = metrics or get_metrics()
        self.states: dict[str, ModelHealthState] = {}
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # ------------------------------------------------------------- lifecycle
    def start(self) -> asyncio.Task:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self.run_loop(), name="health-manager")
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def run_loop(self) -> None:
        interval = self.settings.health_check_interval_s
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("health cycle failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                pass

    # ------------------------------------------------------------- state access
    def state_for(self, model_id: str) -> ModelHealthState:
        if model_id not in self.states:
            self.states[model_id] = ModelHealthState()
        return self.states[model_id]

    # ------------------------------------------------------------- main cycle
    async def run_once(self, now: float | None = None) -> list[dict]:
        """Probe every due model once. Returns summary records (also written to
        the health_events table)."""
        now = time.monotonic() if now is None else now
        records: list[dict] = []
        models = await self.registry.list_models()
        for model in models:
            state = self.state_for(model.id)
            if now < state.next_check_at:
                continue
            adapter = await self.registry.get_adapter(model.provider)
            result = await self._probe(adapter, model.id)
            record = await self._apply_result(model.id, result, now)
            records.append(record)
        return records

    async def _probe(self, adapter, model_id: str):
        try:
            return await asyncio.wait_for(adapter.check_health(), timeout=15.0)
        except TimeoutError:
            from app.providers.base import HealthResult

            return HealthResult(
                ok=False, status=ModelStatus.DOWN, error_type=ErrorType.TIMEOUT,
                message="health probe timed out",
            )
        except Exception as exc:  # noqa: BLE001
            from app.providers.base import HealthResult

            return HealthResult(
                ok=False, status=ModelStatus.DOWN,
                error_type=adapter.detect_error_type(exc), message=str(exc)[:200],
            )

    async def _apply_result(self, model_id: str, result, now: float) -> dict:
        settings = self.settings
        state = self.state_for(model_id)
        previous_status = state.status
        model = await self.registry.get_model(model_id)
        current_db_status = ModelStatus(model.status) if model and model.status in ModelStatus._value2member_map_ else ModelStatus.UNKNOWN

        if result.ok:
            state.consecutive_failures = 0
            state.consecutive_successes += 1
            state.backoff_s = 0.0
            state.next_check_at = now + settings.health_check_interval_s
            if current_db_status in (ModelStatus.DEGRADED, ModelStatus.COOLING):
                new_status = (
                    ModelStatus.ACTIVE
                    if state.consecutive_successes >= settings.health_recover_after_successes
                    else current_db_status
                )
            elif current_db_status == ModelStatus.DOWN:
                new_status = (
                    ModelStatus.DEGRADED
                    if state.consecutive_successes >= settings.health_recover_after_successes
                    else ModelStatus.DOWN
                )
            else:
                new_status = ModelStatus.ACTIVE
        else:
            state.consecutive_successes = 0
            error_type = result.error_type
            if error_type == ErrorType.AUTH_EXPIRED:
                new_status = ModelStatus.AUTH_REQUIRED
            elif error_type in (ErrorType.PAID_REQUIRED, ErrorType.QUOTA_EXHAUSTED):
                new_status = ModelStatus.PAID_REQUIRED
            elif error_type == ErrorType.RATE_LIMITED:
                state.consecutive_failures += 1
                new_status = ModelStatus.COOLING
            else:
                state.consecutive_failures += 1
                if state.consecutive_failures >= settings.health_down_after_failures:
                    new_status = ModelStatus.DOWN
                elif state.consecutive_failures >= settings.health_degrade_after_failures:
                    new_status = ModelStatus.DEGRADED
                else:
                    # Keep the previous status (incl. UNKNOWN for fresh models) —
                    # a single failure must never promote a model.
                    new_status = current_db_status
            state.backoff_s = state.backoff_delay(settings)
            state.next_check_at = now + state.backoff_s

        state.status = new_status
        self.metrics.model_status.labels(model_id=model_id).set(self._status_value(new_status))
        record = {
            "model_id": model_id,
            "status": new_status.value,
            "error_type": result.error_type.value if result.error_type else None,
            "latency_ms": round(result.latency_ms, 1),
            "quota_remaining": result.quota_remaining,
            "message": result.message,
            "failures": state.consecutive_failures,
        }
        # Always record the probe in health_events (audit trail); log only
        # actual transitions — sticky states are re-probed every cycle to
        # detect recovery (e.g. credentials added later).
        await self.registry.set_status(model_id, new_status, message=result.message)
        if new_status != previous_status:
            logger.info(
                "model status change",
                extra={"model_id": model_id, "from": previous_status.value, "to": new_status.value},
            )
        return record

    # ------------------------------------------------------------- passive signals
    async def on_invocation_result(
        self,
        model_id: str,
        *,
        ok: bool,
        error_type: ErrorType | None = None,
        rate_limit: RateLimitInfo | None = None,
        latency_ms: float = 0.0,
    ) -> None:
        """Live-traffic feedback: an immediate, authoritative signal that can
        flip a model out of the eligible pool without waiting for a probe."""
        state = self.state_for(model_id)
        if ok:
            state.consecutive_successes += 1
            state.consecutive_failures = 0
            state.backoff_s = 0.0
            state.next_check_at = min(state.next_check_at, time.monotonic())
            return
        if error_type in (ErrorType.RATE_LIMITED,):
            state.consecutive_failures += 1
            state.next_check_at = time.monotonic() + (rate_limit.retry_after if rate_limit and rate_limit.retry_after else 15.0)
            await self.registry.set_status(model_id, ModelStatus.COOLING, message="rate limited on live traffic")
            state.status = ModelStatus.COOLING
            self.metrics.model_status.labels(model_id=model_id).set(self._status_value(ModelStatus.COOLING))
        elif error_type in (ErrorType.QUOTA_EXHAUSTED, ErrorType.PAID_REQUIRED):
            await self.registry.set_status(model_id, ModelStatus.PAID_REQUIRED, message="quota exhausted on live traffic")
            state.status = ModelStatus.PAID_REQUIRED
            self.metrics.model_status.labels(model_id=model_id).set(self._status_value(ModelStatus.PAID_REQUIRED))
        elif error_type == ErrorType.AUTH_EXPIRED:
            await self.registry.set_status(model_id, ModelStatus.AUTH_REQUIRED, message="auth failure on live traffic")
            state.status = ModelStatus.AUTH_REQUIRED
            self.metrics.model_status.labels(model_id=model_id).set(self._status_value(ModelStatus.AUTH_REQUIRED))
        else:
            state.consecutive_failures += 1
            settings = self.settings
            if state.consecutive_failures >= settings.health_down_after_failures:
                await self.registry.set_status(model_id, ModelStatus.DOWN, message="repeated failures on live traffic")
                state.status = ModelStatus.DOWN
            elif state.consecutive_failures >= settings.health_degrade_after_failures:
                await self.registry.set_status(model_id, ModelStatus.DEGRADED, message="failures on live traffic")
                state.status = ModelStatus.DEGRADED
            self.metrics.model_status.labels(model_id=model_id).set(self._status_value(state.status))

    @staticmethod
    def _status_value(status: ModelStatus) -> float:
        return {
            ModelStatus.ACTIVE: 1.0,
            ModelStatus.DEGRADED: 0.5,
            ModelStatus.COOLING: 0.25,
            ModelStatus.DOWN: 0.0,
            ModelStatus.AUTH_REQUIRED: -1.0,
            ModelStatus.PAID_REQUIRED: -1.0,
            ModelStatus.UNKNOWN: -0.5,
        }.get(status, 0.0)
