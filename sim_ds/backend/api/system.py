"""Health, dashboard overview and audit queries."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.api.deps import get_db, get_principal
from backend.shared.auth import Principal
from backend.shared.canonical import decode_cursor, encode_cursor
from backend.shared.db import Database

router = APIRouter(tags=["system"])


@router.get("/health", response_model=dict[str, Any])
async def health(db: Database = Depends(get_db)) -> dict[str, Any]:
    await db.fetch_one("SELECT 1 AS ok")
    return {"status": "ok", "database": "postgresql" if db.is_postgres else "sqlite"}


@router.get("/stats/overview", response_model=dict[str, Any])
async def overview(
    principal: Principal = Depends(get_principal), db: Database = Depends(get_db)
) -> dict[str, Any]:
    project = principal.project
    scenario = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM scenario WHERE project=:p AND status='active'", {"p": project}
    )
    sets = await db.fetch_one(
        "SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE frozen) AS frozen FROM scenario_set WHERE project=:p",
        {"p": project},
    )
    sources = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM data_source WHERE project=:p", {"p": project}
    )
    tasks = await db.fetch_all(
        """
        SELECT t.status, COUNT(*) AS tasks, COALESCE(SUM(s.total),0) AS cases,
               COALESCE(SUM(s.succeeded),0) AS succeeded, COALESCE(SUM(s.pass_count),0) AS passed
        FROM sim_task t LEFT JOIN task_summary s ON s.task_id=t.id
        WHERE t.project=:p GROUP BY t.status ORDER BY t.status
        """,
        {"p": project},
    )
    total_cases = sum(int(row["cases"]) for row in tasks)
    succeeded = sum(int(row["succeeded"]) for row in tasks)
    passed = sum(int(row["passed"]) for row in tasks)
    queue = await db.fetch_one(
        """
        SELECT COALESCE(SUM(s.queued+s.scheduled),0) AS waiting,
               COALESCE(SUM(s.running),0) AS running
        FROM sim_task t JOIN task_summary s ON s.task_id=t.id
        WHERE t.project=:p AND t.status IN ('queued','scheduled','running','paused')
        """,
        {"p": project},
    )
    return {
        "scenarios": int(scenario["n"]) if scenario else 0,
        "sets": int(sets["n"]) if sets else 0,
        "frozen_sets": int(sets["frozen"]) if sets else 0,
        "sources": int(sources["n"]) if sources else 0,
        "tasks": tasks,
        "total_cases": total_cases,
        "succeeded_cases": succeeded,
        "passed_cases": passed,
        "pass_rate": round(passed * 100.0 / total_cases, 2) if total_cases else 0.0,
        "queue_depth": int(queue["waiting"]) if queue else 0,
        "running_cases": int(queue["running"]) if queue else 0,
    }


@router.get("/audit", response_model=dict[str, Any])
async def audit_log(
    cursor: str | None = None,
    page_size: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    size = max(1, min(page_size, 200))
    params: dict[str, Any] = {"project": principal.project, "limit": size + 1}
    clauses = ["project=:project"]
    if cursor:
        parts = decode_cursor(cursor, 2)
        clauses.append("(created_at, id) < (to_timestamp(:ct), :cid)")
        params["ct"] = float(parts[0])
        params["cid"] = int(parts[1])
    rows = await db.fetch_all(
        f"SELECT * FROM audit_log WHERE {' AND '.join(clauses)} "
        "ORDER BY created_at DESC, id DESC LIMIT :limit",
        params,
    )
    has_more = len(rows) > size
    rows = rows[:size]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(f"{last['created_at'].timestamp():.6f}", last["id"])
    return {"items": rows, "next_cursor": next_cursor}
