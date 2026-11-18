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
from backend.sim.k8s_executor import K8sPoolExecutor
from backend.sim.results import ResultService
from backend.sim.scheduler import Scheduler
from backend.sim.service import TaskService
from backend.sim.worker_service import WorkerService
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


async def test_priority_above_user_limit_is_rejected(
    db: Database, tmp_path: Path, principal: Principal
) -> None:
    tasks, _ = await build_services(db, tmp_path, principal)
    set_row = await db.fetch_one("SELECT id, current_version FROM scenario_set LIMIT 1")
    limited = Principal(
        user="limited", project="default", projects=("default",), admin=False, max_priority=3
    )
    payload = task_payload({"set_id": set_row["id"], "version": set_row["current_version"]})
    payload.priority = 4
    with pytest.raises(AppError) as exc:
        await tasks.submit(payload, limited)
    assert exc.value.code == "PRIORITY_FORBIDDEN"


async def test_remote_worker_claim_and_result_use_scheduler_state_machine(
    db: Database, tmp_path: Path, principal: Principal
) -> None:
    tasks, scheduler = await build_services(db, tmp_path, principal)
    set_row = await db.fetch_one("SELECT id, current_version FROM scenario_set LIMIT 1")
    payload = task_payload({"set_id": set_row["id"], "version": set_row["current_version"]})
    payload.runtime = payload.runtime.model_copy(
        update={
            "binary_uri": "s3://artifacts/worker/engine",
            "binary_checksum": "sha256:" + "a" * 64,
        }
    )
    submitted = await tasks.submit(payload, principal)
    case = await db.fetch_one(
        "SELECT id, scenario_id, scenario_version FROM case_run WHERE task_id=:tid",
        {"tid": submitted["task_id"]},
    )
    await db.execute(
        "UPDATE scenario_version SET file_uri=:uri WHERE scenario_id=:sid AND version=:ver",
        {
            "uri": "s3://artifacts/scenarios/scenario.json",
            "sid": case["scenario_id"],
            "ver": case["scenario_version"],
        },
    )
    await scheduler.claim()
    worker = WorkerService(
        db, scheduler.results, Settings(database_url=db.url, worker_token="private-token")
    )

    assert worker.authenticate("Bearer private-token")
    assert not worker.authenticate("Bearer invalid")
    claimed = await worker.claim("pool-pod-1")
    assert claimed is not None
    assert claimed["case_run_id"] == case["id"]
    assert claimed["scenario_uri"].startswith("s3://")
    assert await worker.start(case["id"], 0, "pool-pod-1")
    assert (await worker.heartbeat(case["id"], 0, "pool-pod-1"))["action"] == "continue"
    result = await worker.report(
        {
            "report_id": "remote-report-1",
            "case_run_id": case["id"],
            "attempt": 0,
            "worker_id": "pool-pod-1",
            "status": "succeeded",
            "metrics": {"metric": {"value": 1.0, "pass": True}},
            "exit_code": 0,
            "reason": "",
            "output_uri": "s3://artifacts/outputs/task/case/",
        }
    )
    assert result["accepted"] is True
    assert (await tasks.get(submitted["task_id"], principal))["status"] == "succeeded"


async def test_k8s_pool_reserves_no_more_than_worker_slots(
    db: Database, tmp_path: Path, principal: Principal
) -> None:
    await seed_metric(db)
    store = FileStore(tmp_path)
    scenarios = ScenarioService(db, store)
    sets = SetService(db, store)
    first = await make_scenario(scenarios, principal, name="first")
    second = await make_scenario(scenarios, principal, name="second")
    set_id = (await sets.create(set_payload([first, second]), principal))["set_id"]
    await sets.freeze(set_id, principal)
    settings = Settings(
        database_url=db.url,
        data_dir=tmp_path,
        scheduler_enabled=False,
        worker_id="k8s-pool-test",
        executor_backend="k8s_pool",
        k8s_pool_replicas=1,
        k8s_worker_slots=1,
        k8s_slot_cpu=2,
        k8s_slot_mem_gb=2,
    )
    results = ResultService(db)
    tasks = TaskService(db, sets)
    scheduler = Scheduler(
        db, settings, results, Expander(db, sets), K8sPoolExecutor(db, settings)
    )
    await scheduler._ensure_worker()
    set_row = await db.fetch_one("SELECT current_version FROM scenario_set WHERE id=:id", {"id": set_id})
    assert set_row is not None
    submitted = await tasks.submit(
        task_payload({"set_id": set_id, "version": set_row["current_version"]}), principal
    )

    await scheduler.claim()

    counts = await db.fetch_one(
        """
        SELECT COUNT(*) FILTER (WHERE status='scheduled') AS scheduled,
               COUNT(*) FILTER (WHERE status='queued') AS queued
        FROM case_run WHERE task_id=:task_id
        """,
        {"task_id": submitted["task_id"]},
    )
    assert counts == {"scheduled": 1, "queued": 1}
