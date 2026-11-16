"""Administrator account and quota management routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.accounts.models import UserCreate, UserUpdate
from backend.accounts.service import AccountService
from backend.api.deps import get_db, get_principal, get_settings
from backend.shared.auth import Principal
from backend.shared.config import Settings
from backend.shared.db import Database
from backend.shared.errors import AppError

router = APIRouter(tags=["users"])


def _require_admin(principal: Principal) -> None:
    if not principal.admin:
        raise AppError("FORBIDDEN", "需要管理员权限", status=403)


@router.get("/users", response_model=dict[str, Any])
async def list_users(
    principal: Principal = Depends(get_principal),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _require_admin(principal)
    return {"items": await AccountService(db, settings).list_users()}


@router.post("/users", response_model=dict[str, Any], status_code=201)
async def create_user(
    body: UserCreate,
    principal: Principal = Depends(get_principal),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _require_admin(principal)
    return await AccountService(db, settings).create_user(body, principal)


@router.put("/users/{user_id}", response_model=dict[str, Any])
async def update_user(
    user_id: str,
    body: UserUpdate,
    principal: Principal = Depends(get_principal),
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _require_admin(principal)
    return await AccountService(db, settings).update_user(user_id, body, principal)
