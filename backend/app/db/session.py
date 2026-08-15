from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.db.base import Base


def build_engine(settings: Settings) -> AsyncEngine:
    kwargs: dict = {"pool_pre_ping": True}
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite":
        # SQLite: no pool_pre_ping, and NullPool so connections are never
        # shared across event loops (TestClient / worker threads).
        from sqlalchemy.pool import NullPool

        kwargs = {"poolclass": NullPool}
    engine = create_async_engine(settings.database_url, **kwargs)
    return engine


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def configure_db(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    """Configure the global engine/session factory (idempotent)."""
    global _engine, _session_factory
    settings = settings or get_settings()
    if _session_factory is None:
        _engine = build_engine(settings)
        _session_factory = build_session_factory(_engine)
    return _session_factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        configure_db()
    assert _session_factory is not None
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_db(settings: Settings | None = None) -> None:
    """Create missing tables. Used for dev/test bootstrap; production uses Alembic."""
    settings = settings or get_settings()
    engine = build_engine(settings)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def dispose_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def database_is_postgres(engine: AsyncEngine) -> bool:
    return make_url(str(engine.url)).get_backend_name() == "postgresql"
