"""Semantic cache service (PostgreSQL + pgvector).

Production path uses a pgvector ``embedding <=> :q`` nearest-neighbour lookup
(HNSW-indexable); non-PostgreSQL dialects (SQLite dev/test) compute cosine in
Python over the intent/language-filtered candidate set. Both paths then apply
the same guardrails — the vector index only narrows candidates, it never
decides safety.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cache.guardrails import cosine, guardrails_pass
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.models import CacheEntry
from app.db.session import database_is_postgres
from app.embeddings.embedder import Embedder
from app.orchestrator.normalize import NormalizedQuery

logger = get_logger("prism.cache")


@dataclass
class CacheHit:
    answer: str
    confidence: float
    similarity: float
    entry_id: str
    source_request_id: str | None


class SemanticCacheService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        settings: Settings | None = None,
    ):
        self.session_factory = session_factory
        self.embedder = embedder
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ lookup
    async def lookup(
        self,
        query: NormalizedQuery,
        *,
        embedding: list[float] | None,
        user_id,
        is_fallback: bool = False,
    ) -> CacheHit | None:
        threshold = (
            self.settings.cache_fallback_similarity
            if is_fallback
            else self.settings.cache_similarity_threshold
        )
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            candidates = await self._candidates(session, query, embedding, user_id, now)
            if not candidates:
                return None
            best_entry, best_sim = None, 0.0
            for entry, sim in candidates:
                ok, failed = guardrails_pass(
                    similarity=sim,
                    intent_q=query.intent,
                    intent_e=entry.intent,
                    lang_q=query.language,
                    lang_e=entry.language,
                    entities_q=query.entities,
                    entities_e=entry.entities or {},
                    time_sensitive_q=query.time_sensitive,
                    entry_created_at=entry.created_at,
                    now=now,
                    confidence=entry.confidence,
                    expires_at=entry.expires_at,
                    threshold=threshold,
                    entity_jaccard_min=self.settings.cache_entity_jaccard_min,
                    confidence_threshold=self.settings.cache_confidence_threshold,
                    time_sensitive_max_age_s=self.settings.cache_time_sensitive_max_age_s,
                )
                if ok and sim > best_sim:
                    best_entry, best_sim = entry, sim
            if best_entry is None:
                return None
            best_entry.last_served_at = now
            best_entry.serve_count = (best_entry.serve_count or 0) + 1
            await session.commit()
            return CacheHit(
                answer=best_entry.best_answer,
                confidence=best_entry.confidence,
                similarity=best_sim,
                entry_id=str(best_entry.id),
                source_request_id=str(best_entry.source_request_id) if best_entry.source_request_id else None,
            )

    async def _candidates(self, session, query, embedding, user_id, now):
        conditions = [
            CacheEntry.expires_at > now,
            CacheEntry.intent == query.intent,
            CacheEntry.language == query.language,
            (CacheEntry.user_id == user_id) | (CacheEntry.is_global.is_(True)),
        ]
        if embedding is not None and await self._is_postgres(session):
            # pgvector nearest-neighbour candidates via cosine distance.
            try:
                distance = text("embedding <=> :q").bindparams(
                    bindparam("q", type_=CacheEntry.__table__.c.embedding.type)
                )
                sim_expr = text("1 - (embedding <=> :q)").bindparams(
                    bindparam("q", type_=CacheEntry.__table__.c.embedding.type)
                )
                stmt = (
                    select(CacheEntry, sim_expr.label("similarity"))
                    .where(*conditions)
                    .order_by(distance)
                    .limit(20)
                )
                rows = await session.execute(stmt, {"q": embedding})
                return [(row[0], float(row[1] or 0.0)) for row in rows.all()]
            except Exception:  # noqa: BLE001 — vector path failure must not break chat
                logger.warning("pgvector candidate lookup failed; falling back to python cosine")
        rows = (await session.execute(select(CacheEntry).where(*conditions).limit(200))).scalars().all()
        out = []
        for entry in rows:
            sim = cosine(embedding, entry.embedding) if embedding is not None else 0.0
            out.append((entry, sim))
        out.sort(key=lambda pair: pair[1], reverse=True)
        return out[:20]

    async def _is_postgres(self, session) -> bool:
        return database_is_postgres(session.get_bind())

    # ------------------------------------------------------------------ store
    async def store(
        self,
        query: NormalizedQuery,
        *,
        answer: str,
        embedding: list[float] | None,
        confidence: float,
        user_id,
        source_request_id=None,
        time_sensitivity: float = 0.0,
    ) -> None:
        """Cache only answers that cleared the judge quality gate (called by
        the orchestrator after scoring)."""
        ttl = self.settings.cache_ttl_hours * 3600
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            existing = (
                await session.scalars(
                    select(CacheEntry).where(
                        CacheEntry.query_hash == query.query_hash,
                        CacheEntry.user_id == user_id,
                    )
                )
            ).first()
            if existing is not None:
                existing.best_answer = answer
                existing.confidence = confidence
                existing.embedding = embedding
                existing.entities = query.entities
                existing.intent = query.intent
                existing.language = query.language
                existing.time_sensitivity = time_sensitivity
                existing.ttl_seconds = ttl
                existing.expires_at = now + timedelta(seconds=ttl)
                existing.source_request_id = source_request_id
            else:
                session.add(
                    CacheEntry(
                        query_hash=query.query_hash,
                        embedding=embedding,
                        intent=query.intent,
                        language=query.language,
                        entities=query.entities,
                        best_answer=answer,
                        confidence=confidence,
                        time_sensitivity=time_sensitivity,
                        ttl_seconds=ttl,
                        expires_at=now + timedelta(seconds=ttl),
                        user_id=user_id,
                        is_global=False,
                        source_request_id=source_request_id,
                    )
                )
            await session.commit()

    # ------------------------------------------------------------------ privacy / ops
    async def purge_user(self, user_id) -> int:
        from sqlalchemy import delete

        async with self.session_factory() as session:
            result = await session.execute(
                delete(CacheEntry).where(CacheEntry.user_id == user_id)
            )
            await session.commit()
            return result.rowcount or 0

    async def purge_for_requests(self, request_ids: list) -> int:
        from sqlalchemy import delete

        if not request_ids:
            return 0
        async with self.session_factory() as session:
            result = await session.execute(
                delete(CacheEntry).where(CacheEntry.source_request_id.in_(request_ids))
            )
            await session.commit()
            return result.rowcount or 0

    async def count(self) -> int:
        from sqlalchemy import func

        async with self.session_factory() as session:
            return (await session.scalar(select(func.count()).select_from(CacheEntry))) or 0

    def embed_sync(self, texts: list[str]) -> list[list[float]]:
        started = time.monotonic()
        embeddings = self.embedder.embed(texts)
        logger.debug("embedded texts", extra={"n": len(texts), "ms": (time.monotonic() - started) * 1000})
        return embeddings
