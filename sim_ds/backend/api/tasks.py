"""Simulation task, control, case and aggregate routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from backend.api.deps import get_principal, get_tasks
from backend.domain.models import SimTaskCreate, TaskControl
from backend.shared.auth import Principal
from backend.sim.service import TaskService

router = APIRouter(tags=["tasks"])


@router.post("/tasks", response_model=dict[str, Any], status_code=201)
async def submit_task(
    body: SimTaskCreate,
    response: Response,
    principal: Principal = Depends(get_principal),
    service: TaskService = Depends(get_tasks),
) -> dict[str, Any]:
    task = await service.submit(body, principal)
    if task.get("status") == "expanding":
        response.status_code = 202
    return task


@router.get("/tasks", response_model=dict[str, Any])
async def list_tasks(
    status: str = "",
    priority: int | None = None,
    search: str = "",
    cursor: str | None = None,
    page_size: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    service: TaskService = Depends(get_tasks),
) -> dict[str, Any]:
    return await service.list_items(
        principal, status=status, priority=priority, search=search, cursor=cursor, page_size=page_size
    )


@router.get("/tasks/{task_id}", response_model=dict[str, Any])
async def get_task(
    task_id: str,
    principal: Principal = Depends(get_principal),
    service: TaskService = Depends(get_tasks),
) -> dict[str, Any]:
    return await service.get(task_id, principal)


@router.post("/tasks/{task_id}:pause", response_model=dict[str, Any], status_code=202)
async def pause_task(
    task_id: str,
    body: TaskControl,
    principal: Principal = Depends(get_principal),
    service: TaskService = Depends(get_tasks),
) -> dict[str, Any]:
    return await service.control(task_id, "pause", body.request_id, principal, body.reason)


@router.post("/tasks/{task_id}:resume", response_model=dict[str, Any], status_code=202)
async def resume_task(
    task_id: str,
    body: TaskControl,
    principal: Principal = Depends(get_principal),
    service: TaskService = Depends(get_tasks),
) -> dict[str, Any]:
    return await service.control(task_id, "resume", body.request_id, principal, body.reason)


@router.post("/tasks/{task_id}:cancel", response_model=dict[str, Any], status_code=202)
async def cancel_task(
    task_id: str,
    body: TaskControl,
    principal: Principal = Depends(get_principal),
    service: TaskService = Depends(get_tasks),
) -> dict[str, Any]:
    return await service.control(task_id, "cancel", body.request_id, principal, body.reason)


@router.get("/tasks/{task_id}/cases", response_model=dict[str, Any])
async def list_cases(
    task_id: str,
    status: str = "",
    outcome: str = "",
    cursor: str | None = None,
    page_size: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(get_principal),
    service: TaskService = Depends(get_tasks),
) -> dict[str, Any]:
    return await service.cases(
        task_id, principal, status=status, outcome=outcome, cursor=cursor, page_size=page_size
    )


@router.get("/tasks/{task_id}/cases/archive", response_model=dict[str, Any])
async def list_archived_cases(
    task_id: str,
    status: str = "",
    cursor: str | None = None,
    page_size: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(get_principal),
    service: TaskService = Depends(get_tasks),
) -> dict[str, Any]:
    return await service.cases_archive(
        task_id, principal, status=status, cursor=cursor, page_size=page_size
    )


@router.get("/tasks/{task_id}/cases/{case_run_id}", response_model=dict[str, Any])
async def get_case(
    task_id: str,
    case_run_id: str,
    principal: Principal = Depends(get_principal),
    service: TaskService = Depends(get_tasks),
) -> dict[str, Any]:
    return await service.case_detail(task_id, case_run_id, principal)


@router.get("/tasks/{task_id}/summary", response_model=dict[str, Any])
async def task_summary(
    task_id: str,
    principal: Principal = Depends(get_principal),
    service: TaskService = Depends(get_tasks),
) -> dict[str, Any]:
    return await service.summary(task_id, principal)


@router.get("/queue/stats", response_model=dict[str, Any])
async def queue_stats(
    principal: Principal = Depends(get_principal),
    service: TaskService = Depends(get_tasks),
) -> dict[str, Any]:
    return await service.queue_stats(principal)
