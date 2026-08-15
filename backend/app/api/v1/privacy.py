"""Privacy endpoints: full user data deletion (GDPR-style right to erasure)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_cache, get_current_user
from app.cache.semantic import SemanticCacheService
from app.core.logging import get_logger
from app.db.models import (
    AuditEvent,
    CacheEntry,
    Conversation,
    Feedback,
    Message,
    ModelInvocation,
    ModelResponse,
    ProviderCredential,
    Request,
    Score,
    Upload,
    User,
)
from app.db.session import get_session
from app.files import delete_stored_file
from app.schemas.admin import DeleteResult

logger = get_logger("prism.privacy")
router = APIRouter(prefix="/me", tags=["privacy"])


@router.delete("/data", response_model=DeleteResult)
async def delete_all_my_data(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    cache: SemanticCacheService = Depends(get_cache),
):
    """Delete every trace of the user: conversations, messages, requests,
    model invocations/responses, scores, feedback, uploads (+ files on disk),
    cache entries derived from their queries, and their audit trail.
    """
    deleted: dict[str, int] = {}

    request_ids = (
        await session.scalars(select(Request.id).where(Request.user_id == user.id))
    ).all()
    conversation_ids = (
        await session.scalars(select(Conversation.id).where(Conversation.user_id == user.id))
    ).all()

    # Responses/scores/invocations derive from requests.
    response_ids = (
        await session.scalars(
            select(ModelResponse.id).where(ModelResponse.request_id.in_(request_ids))
        )
    ).all() if request_ids else []
    if response_ids:
        deleted["scores"] = (await session.execute(delete(Score).where(Score.response_id.in_(response_ids)))).rowcount or 0
    if request_ids:
        deleted["model_responses"] = (await session.execute(delete(ModelResponse).where(ModelResponse.request_id.in_(request_ids)))).rowcount or 0
        deleted["model_invocations"] = (await session.execute(delete(ModelInvocation).where(ModelInvocation.request_id.in_(request_ids)))).rowcount or 0
        deleted["feedback"] = (await session.execute(delete(Feedback).where(Feedback.request_id.in_(request_ids)))).rowcount or 0
    if conversation_ids:
        deleted["messages"] = (await session.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))).rowcount or 0
    if request_ids:
        deleted["requests"] = (await session.execute(delete(Request).where(Request.id.in_(request_ids)))).rowcount or 0
    if conversation_ids:
        deleted["conversations"] = (await session.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))).rowcount or 0

    # Uploads + files on disk.
    uploads = (
        await session.scalars(select(Upload).where(Upload.user_id == user.id))
    ).all()
    files_removed = 0
    for upload in uploads:
        delete_stored_file(upload.stored_path)
        files_removed += 1
    deleted["uploads"] = (await session.execute(delete(Upload).where(Upload.user_id == user.id))).rowcount or 0

    # Cache entries derived from the user's queries (and any user-scoped entries).
    deleted["cache_entries"] = (
        await session.execute(
            delete(CacheEntry).where(
                (CacheEntry.user_id == user.id)
                | CacheEntry.source_request_id.in_(request_ids or [uuid.uuid4()])
            )
        )
    ).rowcount or 0

    # User-scoped provider credentials + audit trail.
    deleted["user_credentials"] = (
        await session.execute(delete(ProviderCredential).where(ProviderCredential.owner_id == user.id))
    ).rowcount or 0
    deleted["audit_events"] = (
        await session.execute(delete(AuditEvent).where(AuditEvent.user_id == user.id))
    ).rowcount or 0

    # Soft-delete the account itself (data retained nowhere else; hard purge
    # runs via the retention job).
    user.deleted_at = datetime.now(UTC)
    user.email = f"deleted-{user.id.hex}@prism.invalid"
    user.password_hash = "!"
    await session.commit()
    logger.info("user data deleted", extra={"user_id": str(user.id), "counts": deleted})
    return DeleteResult(deleted=deleted, files_removed=files_removed, account_deleted=True)
