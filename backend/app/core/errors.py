"""Domain errors + FastAPI exception handlers producing RFC-7807-style bodies."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, request_id_var

logger = get_logger("prism.errors")


class PrismError(Exception):
    """Base domain error. ``code`` is a stable machine-readable slug."""

    code = "internal_error"
    status_code = 500
    message = "Something went wrong."

    def __init__(self, message: str | None = None, *, detail: dict | None = None):
        self.message = message or self.message
        self.detail = detail or {}
        super().__init__(self.message)


class AuthError(PrismError):
    code = "unauthorized"
    status_code = 401
    message = "Authentication required."


class ForbiddenError(PrismError):
    code = "forbidden"
    status_code = 403
    message = "You do not have permission to perform this action."


class NotFoundError(PrismError):
    code = "not_found"
    status_code = 404
    message = "Resource not found."


class ValidationFailed(PrismError):
    code = "validation_failed"
    status_code = 422
    message = "Request validation failed."


class RateLimited(PrismError):
    code = "rate_limited"
    status_code = 429
    message = "Too many requests. Please slow down."


class NoModelAvailable(PrismError):
    """Every model failed or is ineligible and no safe fallback succeeded."""

    code = "no_model_available"
    status_code = 503
    message = "No eligible AI model is currently available."


class RequestQueued(PrismError):
    code = "request_queued"
    status_code = 202
    message = "Request queued and will be processed shortly."


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(PrismError)
    async def prism_error_handler(request: Request, exc: PrismError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "message": exc.message,
                "detail": exc.detail,
                "request_id": request_id_var.get(),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals; log with request id for correlation.
        logger.error("unhandled exception", extra={"path": request.url.path, "exc": str(exc)})
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred.",
                "request_id": request_id_var.get(),
            },
        )
