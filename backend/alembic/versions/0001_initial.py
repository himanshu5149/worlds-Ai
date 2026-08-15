"""Initial Prism AI schema.

Revision ID: 0001
Revises:
Create Date: 2026-08-15

Design note: this bootstrap revision creates the schema from the same
``Base.metadata`` the application uses, so models and schema can never drift.
Later revisions are normal hand-written/diffed migrations. The pgvector
extension and an HNSW index over cache_entries.embedding are created on
PostgreSQL; SQLite is supported for dev/test convenience only.
"""
from __future__ import annotations

from alembic import op

from app.db.base import Base
from app.db import models  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        op.create_index(
            "ix_cache_entries_embedding_hnsw",
            "cache_entries",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
