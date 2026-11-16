"""ScenarioSet routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from backend.api.deps import get_principal, get_sets
from backend.domain.models import SetCreate, SetDerive, SetUpdate
from backend.scenario.sets import SetService
from backend.shared.auth import Principal

router = APIRouter(tags=["sets"])


@router.get("/sets", response_model=dict[str, Any])
async def list_sets(
    frozen: bool | None = None,
    visibility: Literal["private", "public"] | None = None,
    cursor: str | None = None,
    page_size: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    service: SetService = Depends(get_sets),
) -> dict[str, Any]:
    return await service.list_items(
        principal, frozen=frozen, visibility=visibility, cursor=cursor, page_size=page_size
    )


@router.post("/sets", response_model=dict[str, Any], status_code=201)
async def create_set(
    body: SetCreate,
    principal: Principal = Depends(get_principal),
    service: SetService = Depends(get_sets),
) -> dict[str, Any]:
    return await service.create(body, principal)


@router.get("/sets/{set_id}", response_model=dict[str, Any])
async def get_set(
    set_id: str,
    principal: Principal = Depends(get_principal),
    service: SetService = Depends(get_sets),
) -> dict[str, Any]:
    return await service.get(set_id, principal)


@router.put("/sets/{set_id}", response_model=dict[str, Any])
async def update_set(
    set_id: str,
    body: SetUpdate,
    principal: Principal = Depends(get_principal),
    service: SetService = Depends(get_sets),
) -> dict[str, Any]:
    return await service.update(set_id, body, principal)


@router.post("/sets/{set_id}/versions", response_model=dict[str, Any], status_code=201)
async def create_set_version(
    set_id: str,
    body: SetUpdate,
    principal: Principal = Depends(get_principal),
    service: SetService = Depends(get_sets),
) -> dict[str, Any]:
    return await service.update(set_id, body, principal)


@router.post("/sets/{set_id}:freeze", response_model=dict[str, Any])
async def freeze_set(
    set_id: str,
    principal: Principal = Depends(get_principal),
    service: SetService = Depends(get_sets),
) -> dict[str, Any]:
    return await service.freeze(set_id, principal)


@router.post("/sets/{set_id}:derive", response_model=dict[str, Any], status_code=201)
async def derive_set(
    set_id: str,
    body: SetDerive,
    principal: Principal = Depends(get_principal),
    service: SetService = Depends(get_sets),
) -> dict[str, Any]:
    return await service.derive(set_id, body, principal)


@router.get("/sets/{set_id}/members", response_model=dict[str, Any])
async def set_members(
    set_id: str,
    version: int | None = None,
    cursor: str | None = None,
    page_size: int = Query(default=200, ge=1, le=500),
    principal: Principal = Depends(get_principal),
    service: SetService = Depends(get_sets),
) -> dict[str, Any]:
    return await service.members(set_id, principal, version=version, cursor=cursor, page_size=page_size)
