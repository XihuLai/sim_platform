"""Metric five-layer routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.api.deps import get_metrics, get_principal
from backend.domain.models import MetricDef, MetricTemplate, MetricType
from backend.scenario.metrics_service import MetricService
from backend.shared.auth import Principal
from backend.shared.errors import AppError

router = APIRouter(tags=["metrics"])

FIXED_CATEGORIES = ("comfort", "compliance", "safety", "efficiency", "navigation")


def _require_admin(principal: Principal) -> None:
    if not principal.admin:
        raise AppError("FORBIDDEN", "需要管理员权限才能修改 Metric 配置", status=403)


@router.get("/metrics/categories", response_model=dict[str, Any])
async def list_categories(service: MetricService = Depends(get_metrics)) -> dict[str, Any]:
    return {"items": await service.categories()}


@router.post("/metrics/categories", response_model=dict[str, Any], status_code=409)
async def create_category() -> dict[str, Any]:
    raise AppError("FIXED_CATEGORY", "分类集合固定为 5 类，不能新增", status=409)


@router.put("/metrics/categories/{category_id}", response_model=dict[str, Any])
async def update_category(
    category_id: str,
    body: dict[str, Any],
    principal: Principal = Depends(get_principal),
    service: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    _require_admin(principal)
    return await service.update_category(category_id, body, principal)


@router.delete("/metrics/categories/{category_id}", response_model=dict[str, Any], status_code=409)
async def delete_category(category_id: str) -> dict[str, Any]:
    raise AppError("FIXED_CATEGORY", f"分类 {category_id} 固定，不能删除", status=409)


@router.get("/metrics/types", response_model=dict[str, Any])
async def list_types(
    category_id: str | None = None, service: MetricService = Depends(get_metrics)
) -> dict[str, Any]:
    return {"items": await service.types(category_id)}


@router.post("/metrics/types", response_model=dict[str, Any], status_code=201)
async def create_type(
    body: MetricType,
    principal: Principal = Depends(get_principal),
    service: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    _require_admin(principal)
    return await service.create_type(body, principal)


@router.put("/metrics/types/{type_id}", response_model=dict[str, Any])
async def update_type(
    type_id: str,
    body: dict[str, Any],
    principal: Principal = Depends(get_principal),
    service: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    _require_admin(principal)
    return await service.update_type(type_id, body, principal)


@router.delete("/metrics/types/{type_id}", response_model=dict[str, Any])
async def delete_type(
    type_id: str,
    principal: Principal = Depends(get_principal),
    service: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    _require_admin(principal)
    return await service.delete_type(type_id, principal)


@router.get("/metrics/templates", response_model=dict[str, Any])
async def list_templates(
    kind: str | None = None, service: MetricService = Depends(get_metrics)
) -> dict[str, Any]:
    return {"items": await service.templates(kind)}


@router.post("/metrics/templates", response_model=dict[str, Any], status_code=201)
async def create_template(
    body: MetricTemplate,
    principal: Principal = Depends(get_principal),
    service: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    _require_admin(principal)
    return await service.create_template(body, principal)


@router.put("/metrics/templates/{template_id}", response_model=dict[str, Any])
async def update_template(
    template_id: str,
    body: dict[str, Any],
    principal: Principal = Depends(get_principal),
    service: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    _require_admin(principal)
    return await service.update_template(template_id, body, principal)


@router.delete("/metrics/templates/{template_id}", response_model=dict[str, Any])
async def delete_template(
    template_id: str,
    principal: Principal = Depends(get_principal),
    service: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    _require_admin(principal)
    return await service.delete_template(template_id, principal)


@router.get("/metrics/defs", response_model=dict[str, Any])
async def list_defs(
    type_id: str | None = None,
    status: str = "active",
    service: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    return {"items": await service.defs(type_id, status)}


@router.get("/metrics/defs/{def_id}", response_model=dict[str, Any])
async def get_def(
    def_id: str, version: int, service: MetricService = Depends(get_metrics)
) -> dict[str, Any]:
    return await service.get_def(def_id, version)


@router.post("/metrics/defs", response_model=dict[str, Any], status_code=201)
async def create_def(
    body: MetricDef,
    principal: Principal = Depends(get_principal),
    service: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    _require_admin(principal)
    return await service.create_def(body, principal)


@router.put("/metrics/defs/{def_id}", response_model=dict[str, Any])
async def update_def(
    def_id: str,
    body: MetricDef,
    principal: Principal = Depends(get_principal),
    service: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    _require_admin(principal)
    return await service.update_def(def_id, body, principal)


@router.delete("/metrics/defs/{def_id}", response_model=dict[str, Any])
async def delete_def(
    def_id: str,
    principal: Principal = Depends(get_principal),
    service: MetricService = Depends(get_metrics),
) -> dict[str, Any]:
    _require_admin(principal)
    return await service.delete_def(def_id, principal)
