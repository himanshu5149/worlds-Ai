"""Structured JSON logging with request-id context and PII redaction.

Sensitive content (prompts, answers, files) is never logged. Optional extra
fields are passed through :meth:`get_logger`-returned adapter or the
``prism.extra`` contextvar.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from typing import Any

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "user_id", default=None
)

# PII / secret patterns for log redaction. Conservative: redact anything that
# looks like an email, phone, long digit run, key, or token.
_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"\b(?:\+?\d[\d\s().-]{8,}\d)\b"), "<phone>"),
    (re.compile(r"\b\d{13,19}\b"), "<card>"),
    (re.compile(r"\b(?:sk|pk|ak|key|token|secret)[-_][A-Za-z0-9]{8,}\b", re.IGNORECASE), "<secret>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"), "<secret>"),
    (re.compile(r"\b(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64})\b"), "<hash>"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+\b"), "Bearer <redacted>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<ip>"),
]


def redact(text: str) -> str:
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        uid = user_id_var.get()
        if uid:
            payload["user_id"] = uid
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_configured = False


def setup_logging(level: str = "INFO", redact_sensitive: bool = True) -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Silence noisy third-party loggers.
    for noisy in ("httpx", "httpcore", "uvicorn.access", "celery"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


class LoggerAdapter(logging.LoggerAdapter):
    def process(self, msg: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        extra = kwargs.pop("extra", {})
        kwargs["extra"] = {"extra_fields": extra}
        return msg, kwargs


def get_logger(name: str) -> LoggerAdapter:
    return LoggerAdapter(logging.getLogger(name), {})


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:16]
    request_id_var.set(rid)
    return rid
