"""Model registry: persisted catalog + adapter instances + eligibility rules."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.security import decrypt_secret
from app.db.models import Model, ProviderCredential
from app.providers.anthropic import AnthropicAdapter
from app.providers.base import ModelStatus, ProviderAdapter
from app.providers.cohere import CohereAdapter
from app.providers.deepseek import DeepSeekAdapter
from app.providers.gemini import GeminiAdapter
from app.providers.mistral import MistralAdapter
from app.providers.ollama import OllamaAdapter
from app.providers.openai import OpenAIAdapter
from app.providers.xai import XAIAdapter

logger = get_logger("prism.registry")

# Seed catalog. Model IDs are config-driven: edit via the admin API or
# PRISM_SEED_MODELS; the list below is an example set matching each provider's
# official model namespace — verify availability/entitlement per account.
DEFAULT_MODEL_CATALOG: list[dict[str, Any]] = [
    {"id": "openai/gpt-4o-mini", "provider": "openai", "tier": "primary",
     "context_window": 128_000, "routing_weight": 1.0,
     "endpoint": "https://api.openai.com/v1/chat/completions"},
    {"id": "openai/gpt-4o", "provider": "openai", "tier": "primary",
     "context_window": 128_000, "routing_weight": 0.8,
     "endpoint": "https://api.openai.com/v1/chat/completions"},
    {"id": "anthropic/claude-sonnet-4", "provider": "anthropic", "tier": "primary",
     "context_window": 200_000, "routing_weight": 1.0,
     "endpoint": "https://api.anthropic.com/v1/messages"},
    {"id": "gemini/gemini-2.5-flash", "provider": "gemini", "tier": "primary",
     "context_window": 1_000_000, "routing_weight": 1.0,
     "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"},
    {"id": "mistral/mistral-small-latest", "provider": "mistral", "tier": "secondary",
     "context_window": 128_000, "routing_weight": 0.7,
     "endpoint": "https://api.mistral.ai/v1/chat/completions"},
    {"id": "cohere/command-a-03-2025", "provider": "cohere", "tier": "secondary",
     "context_window": 256_000, "routing_weight": 0.7,
     "endpoint": "https://api.cohere.com/v2/chat"},
    {"id": "deepseek/deepseek-chat", "provider": "deepseek", "tier": "secondary",
     "context_window": 64_000, "routing_weight": 0.8,
     "endpoint": "https://api.deepseek.com/chat/completions"},
    {"id": "xai/grok-4", "provider": "xai", "tier": "secondary",
     "context_window": 131_072, "routing_weight": 0.7,
     "endpoint": "https://api.x.ai/v1/chat/completions"},
    {"id": "ollama/llama3.2", "provider": "ollama", "tier": "local", "context_window": 131_072,
     "routing_weight": 0.6, "credentials_required": False,
     "endpoint": "http://localhost:11434/api/chat"},
    {"id": "ollama/qwen2.5:7b", "provider": "ollama", "tier": "local", "context_window": 131_072,
     "routing_weight": 0.5, "credentials_required": False,
     "endpoint": "http://localhost:11434/api/chat"},
]

ADAPTER_CLASSES: dict[str, type[ProviderAdapter]] = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
    "mistral": MistralAdapter,
    "cohere": CohereAdapter,
    "deepseek": DeepSeekAdapter,
    "xai": XAIAdapter,
    "ollama": OllamaAdapter,
}

# Environment variables / settings attributes holding admin API keys per provider.
KEY_SETTINGS = {
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "gemini": "gemini_api_key",
    "mistral": "mistral_api_key",
    "cohere": "cohere_api_key",
    "deepseek": "deepseek_api_key",
    "xai": "xai_api_key",
}

BASE_URL_SETTINGS = {
    "openai": "openai_base_url",
    "anthropic": "anthropic_base_url",
    "gemini": "gemini_base_url",
    "mistral": "mistral_base_url",
    "cohere": "cohere_base_url",
    "deepseek": "deepseek_base_url",
    "xai": "xai_base_url",
    "ollama": "ollama_base_url",
}


@dataclass
class EligibleModel:
    model_id: str
    provider: str
    tier: str
    routing_weight: float
    context_window: int | None
    status: str
    selection_score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class ModelRegistry:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings | None = None,
    ):
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self._adapters: dict[str, ProviderAdapter] = {}
        self._adapter_lock = asyncio.Lock()

    # ------------------------------------------------------------- seeding / reads
    async def seed_defaults(self) -> None:
        async with self.session_factory() as session:
            existing = set((await session.scalars(select(Model.id))).all())
            missing = [m for m in DEFAULT_MODEL_CATALOG if m["id"] not in existing]
            for spec in missing:
                adapter_cls = ADAPTER_CLASSES.get(spec["provider"])
                session.add(
                    Model(
                        id=spec["id"],
                        provider=spec["provider"],
                        endpoint=spec.get("endpoint"),
                        tier=spec.get("tier", "primary"),
                        routing_weight=spec.get("routing_weight", 1.0),
                        context_window=spec.get("context_window"),
                        status=ModelStatus.UNKNOWN.value,
                        credentials_required=spec.get("credentials_required", True),
                        requires_verification=bool(
                            adapter_cls and adapter_cls.requires_verification
                        ),
                        capabilities=(
                            adapter_cls(api_key=None).capabilities() if adapter_cls else {}
                        ),
                        meta={"seed": True, "note": "seed catalog entry"},
                    )
                )
            if missing:
                await session.commit()
                logger.info(
                    "seeded model catalog", extra={"added": [m["id"] for m in missing]}
                )

    async def list_models(self) -> list[Model]:
        async with self.session_factory() as session:
            rows = (await session.scalars(select(Model).order_by(Model.id))).all()
            return list(rows)

    async def get_model(self, model_id: str) -> Model | None:
        async with self.session_factory() as session:
            return await session.get(Model, model_id)

    async def set_status(
        self, model_id: str, status: ModelStatus, *, message: str | None = None
    ) -> None:
        from app.db.models import HealthEvent

        async with self.session_factory() as session:
            model = await session.get(Model, model_id)
            if model is None:
                return
            model.status = status.value
            session.add(HealthEvent(model_id=model_id, status=status.value, message=message))
            await session.commit()

    async def update_weight(
        self, model_id: str, weight: float, *, samples: int | None = None
    ) -> None:
        async with self.session_factory() as session:
            model = await session.get(Model, model_id)
            if model is None:
                return
            model.routing_weight = weight
            if samples is not None:
                meta = dict(model.meta or {})
                meta["feedback_samples"] = samples
                model.meta = meta
            await session.commit()

    # ------------------------------------------------------------- credentials
    async def _stored_credential(self, provider: str, user_id) -> str | None:
        async with self.session_factory() as session:
            row = (
                await session.scalars(
                    select(ProviderCredential)
                    .where(
                        ProviderCredential.provider == provider,
                        ProviderCredential.owner_id == user_id,
                        ProviderCredential.revoked_at.is_(None),
                    )
                    .order_by(ProviderCredential.created_at.desc())
                )
            ).first()
            if row is None:
                return None
            return decrypt_secret(row.key_ref, self.settings)

    def _env_key(self, provider: str) -> str | None:
        attr = KEY_SETTINGS.get(provider)
        if attr is None:
            return None
        return getattr(self.settings, attr, None)

    async def credential_for(self, provider: str, user_id=None) -> str | None:
        """Resolve effective API key: user-provided first, then admin env key."""
        if user_id is not None:
            stored = await self._stored_credential(provider, user_id)
            if stored:
                return stored
        return self._env_key(provider)

    # ------------------------------------------------------------- adapters
    async def get_adapter(self, provider: str, user_id=None) -> ProviderAdapter:
        """Return a cached adapter configured with the best available credential."""
        async with self._adapter_lock:
            cached = self._adapters.get(provider)
            key = await self.credential_for(provider, user_id)
            base_url = getattr(self.settings, BASE_URL_SETTINGS.get(provider, ""), None) or None
            if cached is not None and cached.api_key == key:
                return cached
            cls = ADAPTER_CLASSES.get(provider)
            if cls is None:
                # Config-driven stub for unknown providers — requires verification,
                # never eligible for real traffic.
                from app.providers.stub import StubAdapter

                adapter = StubAdapter(provider_label=provider, settings=self.settings)
            else:
                adapter = cls(api_key=key, base_url=base_url, settings=self.settings)
            self._adapters[provider] = adapter
            return adapter

    async def adapter_states(self) -> dict[str, dict[str, Any]]:
        return {
            provider: adapter.capabilities()
            for provider, adapter in self._adapters.items()
        }

    # ------------------------------------------------------------- eligibility
    async def eligible(
        self,
        *,
        user_id=None,
        limit: int | None = None,
        exclude: set[str] | None = None,
        tiers: tuple[str, ...] | None = None,
    ) -> list[EligibleModel]:
        """Models that may serve traffic right now.

        ACTIVE models score at full routing weight; DEGRADED at half weight;
        UNKNOWN (freshly seeded, not yet probed) is eligible at half weight as
        an optimistic bootstrap — the health manager downgrades on failure.
        COOLING/DOWN/AUTH_REQUIRED/PAID_REQUIRED and unverified stubs are
        hard-excluded. A model without credentials never appears here until an
        official key is supplied.
        """
        exclude = exclude or set()
        models = await self.list_models()
        out: list[EligibleModel] = []
        for m in models:
            if m.id in exclude:
                continue
            if m.status not in (
                ModelStatus.ACTIVE.value,
                ModelStatus.DEGRADED.value,
                ModelStatus.UNKNOWN.value,
            ):
                continue
            if m.requires_verification and not self.settings.allow_mock_providers:
                continue
            if tiers is not None and m.tier not in tiers:
                continue
            adapter = await self.get_adapter(m.provider, user_id)
            if not adapter.has_credentials:
                continue
            # Unverified/stub connectors are never eligible for real traffic
            # unless mock providers are explicitly enabled (dev/demo only).
            if adapter.requires_verification and not self.settings.allow_mock_providers:
                continue
            if m.status == ModelStatus.ACTIVE.value:
                status_multiplier = 1.0
            elif m.status == ModelStatus.DEGRADED.value:
                status_multiplier = 0.5
            else:  # UNKNOWN bootstrap
                status_multiplier = 0.5
            out.append(
                EligibleModel(
                    model_id=m.id,
                    provider=m.provider,
                    tier=m.tier,
                    routing_weight=m.routing_weight,
                    context_window=m.context_window,
                    status=m.status,
                    selection_score=m.routing_weight * status_multiplier,
                    extra={"capabilities": m.capabilities, "endpoint": m.endpoint},
                )
            )
        out.sort(key=lambda e: e.selection_score, reverse=True)
        if limit is not None:
            out = out[:limit]
        return out

    async def credential_status(self) -> list[dict[str, Any]]:
        """Report which providers have official credentials configured."""
        result = []
        for provider, cls in ADAPTER_CLASSES.items():
            key = await self.credential_for(provider)
            result.append(
                {
                    "provider": provider,
                    "has_credentials": bool(key),
                    "credentials_required": cls.credentials_required,
                    "requires_verification": cls.requires_verification,
                }
            )
        return result
