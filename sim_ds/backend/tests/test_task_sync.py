import asyncio
from pathlib import Path

import pytest
from backend.scenario.service import ScenarioService
from backend.scenario.sets import SetService
from backend.shared.auth import Principal
from backend.shared.config import Settings
from backend.shared.db import Database
from backend.shared.errors import AppError
from backend.shared.files import FileStore
from backend.sim.executor import LocalExecutor
from backend.sim.expander import Expander
from backend.sim.results import ResultService
from backend.sim.scheduler import Scheduler
from backend.sim.service import TaskService
from backend.tests.helpers import make_scenario, seed_metric, set_payload, task_payload


async def build_services(
    db: Database, tmp_path: Path, principal: Principal
) -> tuple[TaskService, Scheduler]:
    await seed_metric(db)
    store = FileStore(tmp_path)
    scenarios = ScenarioService(db, store)
    sets = SetService(db, store)
    scenario = await make_scenario(scenarios, principal)
    await sets.freeze((await sets.create(set_payload([scenario]), principal))["set_id"], principal)
    settings = Settings(database_url=db.url, data_dir=tmp_path, scheduler_enabled=False, worker_cpu=8, worker_mem_gb=8)
    results = ResultService(db, heartbeat_timeout_sec=30)
    tasks = TaskService(db, sets)
    scheduler = Scheduler(db, settings, results, Expander(db, sets), LocalExecutor(db, results, settings))
    await scheduler._ensure_worker()
    return tasks, scheduler


async def run_task(tasks: TaskService, scheduler: Scheduler, task_id: str, principal: Principal) -> dict:
    for _ in range(200):
        await scheduler.step()
        await asyncio.sleep(0.05)
        current = await tasks.get(task_id, principal)
        if current["status"] in {"succeeded", "failed", "canceled"}:
            return current
    raise AssertionError("task did not finish")


async def test_sync_task_completes_and_aggregates(db: Database, tmp_path: Path, principal: Principal) -> None:
    tasks, scheduler = await build_services(db, tmp_path, principal)
    set_row = await db.fetch_one("SELECT id, current_version FROM scenario_set LIMIT 1")
    assert set_row is not None
    submitted = await tasks.submit(
        task_payload({"set_id": set_row["id"], "version": set_row["current_version"]}), principal
    )
    assert submitted["status"] == "queued" and submitted["total_cases"] == 1
    finished = await run_task(tasks, scheduler, submitted["task_id"], principal)
    assert finished["status"] == "succeeded"
    summary = await tasks.summary(submitted["task_id"], principal)
    assert summary["task"]["pass_count"] + summary["task"]["fail_count"] == 1
    cases = await tasks.cases(submitted["task_id"], principal)
    assert len(cases["items"]) == 1 and cases["items"][0]["status"] == "succeeded"
    assert cases["items"][0]["metrics"]
    reservations = await db.fetch_all(
        "SELECT released_at FROM resource_reservation WHERE case_run_id=:cid",
        {"cid": cases["items"][0]["case_run_id"]},
    )
    assert len(reservations) == 1 and reservations[0]["released_at"] is not None


async def test_dedup_returns_same_task(db: Database, tmp_path: Path, principal: Principal) -> None:
    tasks, _ = await build_services(db, tmp_path, principal)
    set_row = await db.fetch_one("SELECT id, current_version FROM scenario_set LIMIT 1")
    payload = task_payload({"set_id": set_row["id"], "version": set_row["current_version"]})
    first = await tasks.submit(payload, principal)
    second = await tasks.submit(payload, principal)
    assert second["task_id"] == first["task_id"]
    assert second["deduplicated"] is True


async def test_cross_project_task_read_is_denied(db: Database, tmp_path: Path, principal: Principal) -> None:
    tasks, _ = await build_services(db, tmp_path, principal)
    set_row = await db.fetch_one("SELECT id, current_version FROM scenario_set LIMIT 1")
    submitted = await tasks.submit(
        task_payload({"set_id": set_row["id"], "version": set_row["current_version"]}), principal
    )
    other = Principal(user="other", project="other", projects=("other",), admin=False)
    with pytest.raises(AppError) as exc:
        await tasks.get(submitted["task_id"], other)
    assert exc.value.status == 404
