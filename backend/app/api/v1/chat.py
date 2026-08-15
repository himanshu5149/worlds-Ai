"""Chat endpoints: unified ask-once interface, conversations, feedback,
anonymized candidate comparison, queued-request polling."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_orchestrator
from app.core.errors import ForbiddenError, NotFoundError, ValidationFailed
from app.core.logging import get_logger
from app.db.models import AuditEvent, Conversation, Message, ModelResponse, Request, Upload, User
from app.db.session import get_session
from app.feedback.ema import FeedbackService
from app.orchestrator.fanout import FanoutOrchestrator
from app.schemas.chat import (
    CandidateOut,
    CandidatesResponse,
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationOut,
    FeedbackRequest,
    FeedbackResponse,
    MessageOut,
    RequestStatus,
)

logger = get_logger("prism.chat")
router = APIRouter(prefix="/chat", tags=["chat"])


async def _resolve_attachments(
    session: AsyncSession, user_id: uuid.UUID, attachment_ids: list[uuid.UUID]
) -> str | None:
    parts: list[str] = []
    for file_id in attachment_ids:
        upload = await session.get(Upload, file_id)
        if upload is None or upload.user_id != user_id or upload.deleted_at is not None:
            raise ValidationFailed(f"Attachment {file_id} not found.")
        if upload.extracted_text:
            parts.append(f"[file: {upload.original_name}]\n{upload.extracted_text}")
    return "\n\n".join(parts) if parts else None


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    orchestrator: FanoutOrchestrator = Depends(get_orchestrator),
):
    conversation_id = body.conversation_id
    if conversation_id is not None:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user.id or conversation.deleted_at is not None:
            raise NotFoundError("Conversation not found.")

    history: list[dict[str, str]] = []
    if conversation_id is not None:
        rows = (
            await session.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.deleted_at.is_(None),
                )
                .order_by(Message.created_at)
                .limit(20)
            )
        ).all()
        history = [{"role": m.role, "content": m.content} for m in rows]

    attachments_text = await _resolve_attachments(session, user.id, body.attachments)

    if body.stream:
        outcome = await orchestrator.answer(
            user_id=user.id,
            conversation_id=conversation_id,
            query_text=body.message,
            history=history,
            attachments_text=attachments_text,
        )
        await _append_messages(session, user, conversation_id, body.message, outcome.answer)
        from app.orchestrator.streaming import stream_outcome

        return StreamingResponse(
            stream_outcome(orchestrator, outcome, user.id, conversation_id, history),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    outcome = await orchestrator.answer(
        user_id=user.id,
        conversation_id=conversation_id,
        query_text=body.message,
        history=history,
        attachments_text=attachments_text,
    )
    await _append_messages(session, user, conversation_id, body.message, outcome.answer)
    return ChatResponse(
        request_id=outcome.request_id,
        answer=outcome.answer,
        status=outcome.status,
        from_cache=outcome.from_cache,
        fused=outcome.fused,
        latency_ms=round(outcome.latency_ms, 1),
        message=outcome.message,
        error=outcome.error,
        queue_position=outcome.queue_position,
    )


async def _append_messages(
    session: AsyncSession,
    user: User,
    conversation_id: uuid.UUID | None,
    query_text: str,
    answer: str | None,
) -> None:
    if conversation_id is None:
        title = query_text.strip()[:60]
        conversation = Conversation(user_id=user.id, title=title)
        session.add(conversation)
        await session.flush()
        conversation_id = conversation.id
    session.add(Message(conversation_id=conversation_id, role="user", content=query_text))
    if answer:
        session.add(Message(conversation_id=conversation_id, role="assistant", content=answer))
    await session.commit()


# ------------------------------------------------------------------ conversations
@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    rows = (
        await session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user.id, Conversation.deleted_at.is_(None))
            .order_by(Conversation.updated_at.desc())
            .limit(100)
        )
    ).all()
    return [ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at) for c in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id or conversation.deleted_at is not None:
        raise NotFoundError("Conversation not found.")
    messages = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.deleted_at.is_(None))
            .order_by(Message.created_at)
        )
    ).all()
    requests = (
        await session.scalars(
            select(Request).where(Request.conversation_id == conversation_id).order_by(Request.created_at)
        )
    ).all()
    return ConversationDetail(
        conversation=ConversationOut(
            id=conversation.id, title=conversation.title,
            created_at=conversation.created_at, updated_at=conversation.updated_at,
        ),
        messages=[MessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at) for m in messages],
        requests=[
            {
                "request_id": str(r.id), "status": r.status, "cache_hit": r.cache_hit,
                "latency_ms": r.latency_ms, "created_at": r.created_at.isoformat(),
            }
            for r in requests
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise NotFoundError("Conversation not found.")
    await session.execute(
        delete(Message).where(Message.conversation_id == conversation_id)
    )
    await session.execute(
        delete(Conversation).where(Conversation.id == conversation_id)
    )
    session.add(
        AuditEvent(user_id=user.id, action="conversation.delete", resource_type="conversation",
                   resource_id=str(conversation_id))
    )
    await session.commit()


# ------------------------------------------------------------------ feedback
@router.post("/{request_id}/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request_id: uuid.UUID,
    body: FeedbackRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    request = await session.get(Request, request_id)
    if request is None or (request.user_id is not None and request.user_id != user.id):
        raise NotFoundError("Request not found.")
    from app.db.session import get_session_factory

    service = FeedbackService(get_session_factory())
    updates = await service.record_and_update(
        request_id=request_id, user_id=user.id, rating=body.rating, comment=body.comment
    )
    return FeedbackResponse(
        accepted=True,
        weight_updates=[
            {"model_id": u.model_id, "old_weight": u.old_weight,
             "new_weight": u.new_weight, "effective_alpha": u.effective_alpha}
            for u in updates
        ],
    )


# ------------------------------------------------------------------ candidates (anonymized by default)
@router.get("/{request_id}/candidates", response_model=CandidatesResponse)
async def get_candidates(
    request_id: uuid.UUID,
    reveal: bool = False,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    request = await session.get(Request, request_id)
    if request is None or (request.user_id is not None and request.user_id != user.id):
        raise NotFoundError("Request not found.")
    if reveal and user.role != "admin":
        raise ForbiddenError("Only admins may reveal model identities.")
    responses = (
        await session.scalars(
            select(ModelResponse)
            .where(ModelResponse.request_id == request_id)
            .order_by(ModelResponse.score.desc())
        )
    ).all()
    if reveal:
        session.add(
            AuditEvent(
                user_id=user.id, action="admin.reveal_candidates", resource_type="request",
                resource_id=str(request_id), detail={"count": len(responses)},
            )
        )
        await session.commit()
    max_score = max((r.score or 0.0) for r in responses) or 1.0
    candidates = []
    for i, r in enumerate(responses):
        candidates.append(
            CandidateOut(
                label=f"Candidate {chr(ord('A') + i)}",
                text=r.raw_answer,
                score_pct=round(100 * (r.score or 0.0) / max_score),
                is_winner=r.selected,
                fused=r.fused,
                model_id=r.model_id if reveal else None,
                provider=r.model_id.split("/", 1)[0] if reveal else None,
            )
        )
    return CandidatesResponse(request_id=request_id, revealed=reveal, candidates=candidates)


# ------------------------------------------------------------------ queued request polling
@router.get("/requests/{request_id}", response_model=RequestStatus)
async def get_request_status(
    request_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    request = await session.get(Request, request_id)
    if request is None or (request.user_id is not None and request.user_id != user.id):
        raise NotFoundError("Request not found.")
    return RequestStatus(
        request_id=request.id, status=request.status,
        answer=request.final_answer if request.status == "completed" else None,
        error=request.error_type,
    )
