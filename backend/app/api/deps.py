"""Shared API dependencies: auth, RBAC, service accessors."""
from __future__ import annotations

import uuid

import jwt as pyjwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AuthError, ForbiddenError
from app.core.logging import user_id_var
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_session


def get_app_settings(request: Request) -> Settings:
    """The app's configured settings (not the process-global defaults)."""
    return request.app.state.settings


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> User:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise AuthError("Missing bearer token.")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token, settings)
    except pyjwt.ExpiredSignatureError:
        raise AuthError("Token expired.") from None
    except pyjwt.InvalidTokenError:
        raise AuthError("Invalid token.") from None
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise AuthError("Invalid token payload.") from None
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AuthError("Account not found or deleted.")
    user_id_var.set(str(user.id))
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise ForbiddenError("Admin role required.")
    return user


def get_registry(request: Request):
    return request.app.state.registry


def get_orchestrator(request: Request):
    return request.app.state.orchestrator


def get_health(request: Request):
    return request.app.state.health


def get_cache(request: Request):
    return request.app.state.cache
