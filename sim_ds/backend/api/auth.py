"""Login, current-user and logout routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from backend.accounts.models import LoginRequest
from backend.accounts.service import AccountService
from backend.api.deps import get_db, get_principal, get_settings
from backend.shared.auth import Principal
from backend.shared.config import Settings
from backend.shared.db import Database

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=dict[str, Any])
async def login(
    body: LoginRequest,
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return await AccountService(db, settings).login(body.username, body.password)


@router.get("/auth/me", response_model=dict[str, Any])
async def me(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return {
        "username": principal.user,
        "role": principal.role,
        "project": principal.project,
        "admin": principal.admin,
        "max_priority": principal.max_priority,
        "max_running_cases": principal.max_running_cases,
        "max_cpu": principal.max_cpu,
        "max_mem_gb": principal.max_mem_gb,
        "max_gpu": principal.max_gpu,
    }


@router.post("/auth/logout", response_model=dict[str, Any])
async def logout(
    request: Request,
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if token:
        await AccountService(db, settings).logout(token)
    return {"ok": True}
