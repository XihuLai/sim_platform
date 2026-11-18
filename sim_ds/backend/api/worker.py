"""Private worker callback API; workers never connect directly to PostgreSQL."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field

from backend.shared.errors import AppError
from backend.sim.worker_service import WorkerService

router = APIRouter(prefix="/internal/worker", tags=["worker"])


class WorkerClaim(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    capacity: dict[str, int] = Field(default_factory=dict)


class WorkerFact(BaseModel):
    case_run_id: str
    attempt: int = Field(ge=0)
    worker_id: str = Field(min_length=1, max_length=128)


class WorkerResult(WorkerFact):
    report_id: str
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    exit_code: int | None = None
    reason: str = ""
    output_uri: str = ""


def get_worker_service(request: Request) -> WorkerService:
    return request.app.state.worker_service  # type: ignore[no-any-return]


async def require_worker(
    authorization: str | None = Header(default=None),
    service: WorkerService = Depends(get_worker_service),
) -> None:
    if not service.authenticate(authorization):
        raise AppError("WORKER_UNAUTHENTICATED", "Worker 令牌无效", status=401)


@router.post("/claim", response_model=dict[str, Any])
async def claim(
    body: WorkerClaim,
    _: None = Depends(require_worker),
    service: WorkerService = Depends(get_worker_service),
) -> dict[str, Any]:
    return {"case": await service.claim(body.worker_id, body.capacity)}


@router.post("/start", response_model=dict[str, Any])
async def report_start(
    body: WorkerFact,
    _: None = Depends(require_worker),
    service: WorkerService = Depends(get_worker_service),
) -> dict[str, Any]:
    accepted = await service.start(body.case_run_id, body.attempt, body.worker_id)
    return {"accepted": accepted}


@router.post("/heartbeat", response_model=dict[str, Any])
async def heartbeat(
    body: WorkerFact,
    _: None = Depends(require_worker),
    service: WorkerService = Depends(get_worker_service),
) -> dict[str, Any]:
    return await service.heartbeat(body.case_run_id, body.attempt, body.worker_id)


@router.post("/result", response_model=dict[str, Any])
async def report_result(
    body: WorkerResult,
    _: None = Depends(require_worker),
    service: WorkerService = Depends(get_worker_service),
) -> dict[str, Any]:
    return await service.report(body.model_dump())
