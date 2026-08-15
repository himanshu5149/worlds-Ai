"""Declarative base, naming conventions and cross-dialect column types.

``EmbeddingVector`` compiles to a real pgvector ``vector(N)`` on PostgreSQL and
to a JSON float list on other dialects (SQLite for tests/dev) so the same model
definition runs everywhere.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# JSON on SQLite, JSONB on PostgreSQL.
JSONBType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class EmbeddingVector(TypeDecorator):
    """vector(N) via pgvector on PostgreSQL; JSON list elsewhere."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int):
        self.dim = dim
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(v) for v in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if hasattr(value, "tolist"):  # numpy array (pgvector)
            value = value.tolist()
        return [float(v) for v in value]
