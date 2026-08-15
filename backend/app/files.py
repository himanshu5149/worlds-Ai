"""File storage: validation, extraction, deletion.

Uploaded files are untrusted input:
* size capped (default 10 MB), MIME whitelist + magic-byte sniffing
* extracted text is wrapped in <user_document> tags by the orchestrator so a
  document cannot smuggle prompt-injection instructions
* files are stored under random opaque names, never the original filename
"""
from __future__ import annotations

import hashlib
import re
import uuid
import zipfile
from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings, get_settings
from app.core.errors import ValidationFailed

_ALLOWED_TYPES: dict[str, set[str]] = {
    "text/plain": {".txt", ".log", ".md"},
    "text/markdown": {".md"},
    "text/csv": {".csv"},
    "application/json": {".json"},
    "application/pdf": {".pdf"},
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {".docx"},
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
}

_MAGIC_BYTES: dict[str, tuple[bytes, int]] = {
    "application/pdf": (b"%PDF", 4),
    "image/png": (b"\x89PNG", 4),
    "image/jpeg": (b"\xff\xd8\xff", 3),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (b"PK\x03\x04", 4),
}

_TEXT_EXTRACTABLE = {"text/plain", "text/markdown", "text/csv", "application/json",
                     "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}

MAX_EXTRACTED_CHARS = 20_000


def validate_upload(filename: str, mime: str, data: bytes, settings: Settings) -> str:
    """Return the canonical mime type or raise ValidationFailed."""
    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        raise ValidationFailed(f"File exceeds the {settings.max_upload_mb} MB limit.")
    ext = Path(filename).suffix.lower()
    if mime not in _ALLOWED_TYPES or ext not in _ALLOWED_TYPES[mime]:
        raise ValidationFailed(
            "Unsupported file type. Allowed: txt, md, csv, json, pdf, docx, png, jpg."
        )
    magic = _MAGIC_BYTES.get(mime)
    if magic is not None and not data.startswith(magic[0]):
        raise ValidationFailed("File content does not match its declared type.")
    if ext == ".docx" and not zipfile.is_zipfile(_ensure_bytesio(data)):
        raise ValidationFailed("Invalid .docx file.")
    return mime


def _ensure_bytesio(data: bytes):
    import io

    return io.BytesIO(data)


def extract_text(filename: str, mime: str, data: bytes) -> str | None:
    """Best-effort text extraction. Returns None for binary/unsupported."""
    if mime not in _TEXT_EXTRACTABLE:
        return None
    try:
        if mime in ("text/plain", "text/markdown", "text/csv", "application/json"):
            text = data.decode("utf-8", errors="replace")
        elif mime == "application/pdf":
            from io import BytesIO

            from pypdf import PdfReader

            reader = PdfReader(BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        elif mime.endswith("wordprocessingml.document"):
            text = _extract_docx_text(data)
        else:
            return None
    except Exception:  # noqa: BLE001 — extraction failure must never block the chat
        return None
    if not text or not text.strip():
        return None
    return text.strip()[:MAX_EXTRACTED_CHARS]


def _extract_docx_text(data: bytes) -> str:
    with zipfile.ZipFile(_ensure_bytesio(data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    paragraphs = re.findall(r"<w:p[ >].*?</w:p>", xml, re.DOTALL)
    lines = []
    for para in paragraphs:
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, re.DOTALL)
        lines.append("".join(texts))
    return "\n".join(lines)


async def save_upload(file: UploadFile, user_id, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    data = await file.read()
    filename = file.filename or "upload"
    mime = validate_upload(filename, file.content_type or "", data, settings)
    storage = Path(settings.storage_dir)
    storage.mkdir(parents=True, exist_ok=True)
    opaque_name = f"{uuid.uuid4().hex}"
    ext = Path(filename).suffix.lower()
    stored_path = storage / f"{opaque_name}{ext}"
    stored_path.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    return {
        "original_name": filename,
        "stored_path": str(stored_path),
        "mime_type": mime,
        "size_bytes": len(data),
        "sha256": sha,
        "extracted_text": extract_text(filename, mime, data),
    }


def delete_stored_file(stored_path: str) -> None:
    try:
        Path(stored_path).unlink(missing_ok=True)
    except OSError:
        pass
