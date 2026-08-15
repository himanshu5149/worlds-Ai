"""Central configuration via pydantic-settings.

All values are overridable through environment variables (prefix ``PRISM_``) or a
``.env`` file. Provider API keys accept both the prefixed name and the plain
community-standard name (e.g. ``PRISM_OPENAI_API_KEY`` or ``OPENAI_API_KEY``).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="PRISM_", extra="ignore", case_sensitive=False
    )

    # ---- runtime -----------------------------------------------------------
    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]

    # ---- data stores ---------------------------------------------------------
    database_url: str = "postgresql+asyncpg://prism:prism@localhost:5432/prism"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: str = "./data/uploads"
    max_upload_mb: int = 10

    # ---- security -------------------------------------------------------------
    jwt_secret: str = "CHANGE_ME_IN_PRODUCTION"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    # Fernet key (base64, 32 bytes) for encrypting stored provider credentials.
    credential_encryption_key: str | None = None
    pii_redact_logs: bool = True
    rate_limit_chat_per_minute: int = 20
    auth_rate_limit_per_minute: int = 10

    # ---- fan-out orchestration ---------------------------------------------------
    max_fanout_models: int = 4
    soft_timeout_s: float = 8.0
    hard_timeout_s: float = 20.0
    fallback_timeout_s: float = 15.0
    max_fanout_retries: int = 0  # no blind retries; errors drive backoff/fallback

    # ---- health manager -----------------------------------------------------------
    health_check_interval_s: float = 30.0
    health_degrade_after_failures: int = 2
    health_down_after_failures: int = 5
    health_recover_after_successes: int = 2
    health_backoff_base_s: float = 30.0
    health_backoff_max_s: float = 900.0
    enable_background_tasks: bool = True

    # ---- semantic cache -------------------------------------------------------------
    cache_similarity_threshold: float = 0.92
    cache_confidence_threshold: float = 0.85
    cache_ttl_hours: int = 24
    cache_entity_jaccard_min: float = 0.6
    cache_time_sensitive_max_age_s: int = 900  # 15 min freshness window
    cache_fallback_similarity: float = 0.95   # stricter threshold when cache is the fallback
    embedding_dim: int = 1536  # matches OpenAI text-embedding-3-small; local hasher projects to this

    # ---- judge / scoring ------------------------------------------------------------
    judge_quality_gate: float = 0.55
    judge_fusion_min_score: float = 0.60
    judge_fusion_score_margin: float = 0.08
    judge_fusion_sentence_sim: float = 0.87
    judge_max_answer_tokens: int = 1500
    judge_enable_local_model: bool = False  # optional local tie-breaker judge

    # ---- feedback EMA ---------------------------------------------------------------
    feedback_ema_alpha: float = 0.10
    feedback_target_up: float = 1.15
    feedback_target_down: float = 0.85
    feedback_weight_min: float = 0.10
    feedback_weight_max: float = 2.50
    feedback_min_samples: int = 5

    # ---- theme (exposed for the pastel design system, used by docs/admin UI) ---------
    pastel_theme_primary: str = "#E9D5FF"  # lavender
    pastel_theme_mint: str = "#A7F3D0"
    pastel_theme_peach: str = "#FED7AA"
    pastel_theme_blue: str = "#BFDBFE"
    pastel_theme_bg: str = "#FAFAF9"
    pastel_theme_dark_bg: str = "#0F172A"

    # ---- provider credentials (official APIs only) -------------------------------------
    openai_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "PRISM_OPENAI_API_KEY")
    )
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "PRISM_ANTHROPIC_API_KEY")
    )
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    gemini_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "PRISM_GEMINI_API_KEY")
    )
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    mistral_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("MISTRAL_API_KEY", "PRISM_MISTRAL_API_KEY")
    )
    mistral_base_url: str = "https://api.mistral.ai/v1"
    cohere_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("COHERE_API_KEY", "PRISM_COHERE_API_KEY")
    )
    cohere_base_url: str = "https://api.cohere.com/v2"
    deepseek_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("DEEPSEEK_API_KEY", "PRISM_DEEPSEEK_API_KEY")
    )
    deepseek_base_url: str = "https://api.deepseek.com"
    xai_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("XAI_API_KEY", "PRISM_XAI_API_KEY")
    )
    xai_base_url: str = "https://api.x.ai/v1"
    ollama_base_url: str = "http://localhost:11434"

    # ---- provider behaviour ----------------------------------------------------------
    provider_timeout_s: float = 60.0
    provider_max_tokens: int = 1024
    provider_temperature: float = 0.4
    # Mock/stub connectors are disabled unless explicitly enabled (dev/demo only).
    allow_mock_providers: bool = False

    # ---- embeddings ------------------------------------------------------------------
    embedding_backend: Literal["local-hash", "openai", "ollama"] = "local-hash"
    embedding_model: str = ""  # e.g. "text-embedding-3-small" (openai) or "nomic-embed-text" (ollama)

    # ---- queue --------------------------------------------------------------------------
    queue_enabled: bool = False

    # ---- observability -------------------------------------------------------------------
    otel_enabled: bool = False
    otel_exporter_endpoint: str = "http://localhost:4317"

    @property
    def is_dev(self) -> bool:
        return self.env in ("dev", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()
