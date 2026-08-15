from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_current_user
from app.core.config import Settings
from app.core.errors import AuthError, RateLimited
from app.core.logging import get_logger
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import AuditEvent, User
from app.db.session import get_session
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut

logger = get_logger("prism.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory sliding window for auth endpoints (per IP). Production: move to Redis.
_windows: dict[str, deque] = defaultdict(deque)
_WINDOW_S = 60


def _check_rate_limit(request: Request, settings: Settings) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _windows[ip]
    while window and now - window[0] > _WINDOW_S:
        window.popleft()
    if len(window) >= settings.auth_rate_limit_per_minute:
        raise RateLimited("Too many auth attempts. Please wait a minute.")
    window.append(now)


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    _check_rate_limit(request, settings)
    existing = (await session.scalars(select(User).where(User.email == body.email))).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail={"error": "email_taken", "message": "An account with this email already exists."})
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role="admin" if settings.env == "dev" and body.email.endswith("@admin.prism") else "user",
    )
    session.add(user)
    await session.commit()
    session.add(
        AuditEvent(user_id=user.id, action="auth.register", resource_type="user", resource_id=str(user.id))
    )
    await session.commit()
    logger.info("user registered", extra={"user_id": str(user.id)})
    return TokenResponse(
        access_token=create_access_token(user.id, user.role, settings),
        role=user.role,
        expires_in_minutes=settings.access_token_minutes,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
):
    _check_rate_limit(request, settings)
    user = (await session.scalars(select(User).where(User.email == body.email))).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise AuthError("Invalid email or password.")
    if user.deleted_at is not None:
        raise AuthError("Account deleted.")
    session.add(
        AuditEvent(user_id=user.id, action="auth.login", resource_type="user", resource_id=str(user.id))
    )
    await session.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, user.role, settings),
        role=user.role,
        expires_in_minutes=settings.access_token_minutes,
    )


@router.post("/logout", status_code=204)
async def logout(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    session.add(
        AuditEvent(user_id=user.id, action="auth.logout", resource_type="user", resource_id=str(user.id))
    )
    await session.commit()


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut(
        id=user.id, email=user.email, role=user.role,
        display_name=user.display_name, preferences=user.preferences or {},
    )
