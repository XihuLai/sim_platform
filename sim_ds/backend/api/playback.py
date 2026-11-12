"""Playback source and chunk routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.api.deps import get_playback, get_principal
from backend.domain.models import DataSourceCreate, ExtractRequest
from backend.playback.service import PlaybackService
from backend.shared.auth import Principal

router = APIRouter(tags=["playback"])


@router.post("/sources:extract", response_model=dict[str, Any], status_code=201)
async def extract_source(
    body: ExtractRequest,
    principal: Principal = Depends(get_principal),
    service: PlaybackService = Depends(get_playback),
) -> dict[str, Any]:
    return await service.extract(body, principal)


@router.post("/sources", response_model=dict[str, Any], status_code=201)
async def create_source(
    body: DataSourceCreate,
    principal: Principal = Depends(get_principal),
    service: PlaybackService = Depends(get_playback),
) -> dict[str, Any]:
    return await service.create(body, principal)


@router.get("/sources", response_model=dict[str, Any])
async def list_sources(
    cursor: str | None = None,
    page_size: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    service: PlaybackService = Depends(get_playback),
) -> dict[str, Any]:
    return await service.list_items(principal, cursor=cursor, page_size=page_size)


@router.post("/sources:index", response_model=dict[str, Any], status_code=202)
async def index_source(
    body: dict[str, str],
    principal: Principal = Depends(get_principal),
    service: PlaybackService = Depends(get_playback),
) -> dict[str, Any]:
    return await service.index(body.get("source_id", ""), principal)


@router.get("/sources/{source_id}", response_model=dict[str, Any])
async def get_source(
    source_id: str,
    principal: Principal = Depends(get_principal),
    service: PlaybackService = Depends(get_playback),
) -> dict[str, Any]:
    return await service.get(source_id, principal)


@router.get("/sources/{source_id}/status", response_model=dict[str, Any])
async def source_status(
    source_id: str,
    principal: Principal = Depends(get_principal),
    service: PlaybackService = Depends(get_playback),
) -> dict[str, Any]:
    return await service.status(source_id, principal)


@router.get("/sources/{source_id}/channels", response_model=dict[str, Any])
async def source_channels(
    source_id: str,
    principal: Principal = Depends(get_principal),
    service: PlaybackService = Depends(get_playback),
) -> dict[str, Any]:
    return await service.channels(source_id, principal)


@router.get("/sources/{source_id}/chunk", response_model=dict[str, Any])
async def source_chunk(
    source_id: str,
    channel: str,
    ts: int,
    span: int = 2000,
    principal: Principal = Depends(get_principal),
    service: PlaybackService = Depends(get_playback),
) -> dict[str, Any]:
    return await service.chunk(source_id, channel, ts, span, principal)


@router.get("/sources/{source_id}/frame", response_model=dict[str, Any])
async def source_frame(
    source_id: str,
    channel: str,
    ts: int,
    idx: int | None = None,
    principal: Principal = Depends(get_principal),
    service: PlaybackService = Depends(get_playback),
) -> dict[str, Any]:
    return await service.frame(source_id, channel, ts, idx, principal)
