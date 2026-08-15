"""API v1 router aggregation."""
from fastapi import APIRouter

from app.api.v1 import admin, auth, chat, files, privacy

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(files.router)
api_router.include_router(admin.router)
api_router.include_router(privacy.router)
