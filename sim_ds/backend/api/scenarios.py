"""Scenario CRUD, versions and template usage."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from backend.api.deps import get_metrics, get_principal, get_scenarios
from backend.domain.models import ScenarioCopy, ScenarioCreate, ScenarioUpdate
from backend.scenario.metrics_service import MetricService
from backend.scenario.service import ScenarioService
from backend.shared.auth import Principal

router = APIRouter(tags=["scenarios"])


@router.get("/scenarios", response_model=dict[str, Any])
async def list_scenarios(
    search: str = "",
    tag: str = "",
    tags: list[str] | None = Query(default=None),
    tag_expr: str = "",
    tag_mode: Literal["and", "or"] = Query(default="or"),
    status: str = "active",
    cursor: str | None = None,
    page_size: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    service: ScenarioService = Depends(get_scenarios),
) -> dict[str, Any]:
    return await service.list_items(
        principal,
        search=search,
        tag=tag,
        tags=tags,
        tag_expr=tag_expr,
        tag_mode=tag_mode,
        status=status,
        cursor=cursor,
        page_size=page_size,
    )


@router.get("/tags", response_model=dict[str, Any])
async def list_tags(
    search: str = "",
    page_size: int = Query(default=200, ge=1, le=500),
    principal: Principal = Depends(get_principal),
    service: ScenarioService = Depends(get_scenarios),
) -> dict[str, Any]:
    return {"items": await service.tags(principal, search=search, page_size=page_size)}


@router.post("/scenarios/{scenario_id}:copy", response_model=dict[str, Any], status_code=201)
async def copy_scenario(
    scenario_id: str,
    body: ScenarioCopy,
    principal: Principal = Depends(get_principal),
    service: ScenarioService = Depends(get_scenarios),
) -> dict[str, Any]:
    return await service.copy(scenario_id, principal, body.name)


@router.post("/scenarios", response_model=dict[str, Any], status_code=201)
async def create_scenario(
    body: ScenarioCreate,
    principal: Principal = Depends(get_principal),
    service: ScenarioService = Depends(get_scenarios),
) -> dict[str, Any]:
    return await service.create(body, principal)


@router.get("/scenarios/{scenario_id}", response_model=dict[str, Any])
async def get_scenario(
    scenario_id: str,
    version: int | None = None,
    principal: Principal = Depends(get_principal),
    service: ScenarioService = Depends(get_scenarios),
) -> dict[str, Any]:
    return await service.get(scenario_id, principal, version)


@router.put("/scenarios/{scenario_id}", response_model=dict[str, Any])
async def update_scenario(
    scenario_id: str,
    body: ScenarioUpdate,
    principal: Principal = Depends(get_principal),
    service: ScenarioService = Depends(get_scenarios),
) -> dict[str, Any]:
    return await service.update(scenario_id, body, principal)


@router.delete("/scenarios/{scenario_id}", response_model=dict[str, Any])
async def delete_scenario(
    scenario_id: str,
    hard: bool = False,
    principal: Principal = Depends(get_principal),
    service: ScenarioService = Depends(get_scenarios),
) -> dict[str, Any]:
    return await service.archive(scenario_id, principal, hard=hard)


@router.get("/scenarios/{scenario_id}/versions", response_model=dict[str, Any])
async def scenario_versions(
    scenario_id: str,
    principal: Principal = Depends(get_principal),
    service: ScenarioService = Depends(get_scenarios),
) -> dict[str, Any]:
    return {"items": await service.versions(scenario_id, principal)}


@router.get("/metrics/templates/{template_id}/scenarios", response_model=dict[str, Any])
async def template_scenarios(
    template_id: str,
    principal: Principal = Depends(get_principal),
    service: ScenarioService = Depends(get_scenarios),
    metrics: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    await metrics.templates()
    return {"items": await service.template_usage(template_id, principal)}
