"""File upload endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_current_user
from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationFailed
from app.db.models import Upload, User
from app.db.session import get_session
from app.files import delete_stored_file, save_upload

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload", status_code=201)
async def upload_file(
    file: UploadFile,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    try:
        saved = await save_upload(file, user.id, settings)
    except ValidationFailed:
        raise
    except Exception:
        raise ValidationFailed("Could not read the uploaded file.")
    upload = Upload(
        user_id=user.id,
        original_name=saved["original_name"],
        stored_path=saved["stored_path"],
        mime_type=saved["mime_type"],
        size_bytes=saved["size_bytes"],
        sha256=saved["sha256"],
        extracted_text=saved["extracted_text"],
    )
    session.add(upload)
    await session.commit()
    return {
        "file_id": str(upload.id),
        "original_name": upload.original_name,
        "mime_type": upload.mime_type,
        "size_bytes": upload.size_bytes,
        "extracted_chars": len(upload.extracted_text or ""),
    }


@router.delete("/{file_id}", status_code=204)
async def delete_file(
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    upload = await session.get(Upload, file_id)
    if upload is None or upload.user_id != user.id:
        raise NotFoundError("File not found.")
    delete_stored_file(upload.stored_path)
    upload.deleted_at = upload.deleted_at or __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    )
    await session.commit()
