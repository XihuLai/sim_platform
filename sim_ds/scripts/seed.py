#!/usr/bin/env python3
"""Seed a realistic demo corpus through the real services and scheduler."""

from __future__ import annotations

import argparse
import asyncio
import shutil
from typing import Any

from backend.domain.models import (
    ExtractRequest,
    RuntimeConfig,
    SimTaskCreate,
)
from backend.playback.service import PlaybackService
from backend.scenario.metrics_service import MetricService
from backend.scenario.service import ScenarioService
from backend.scenario.sets import SetService
from backend.shared.auth import Principal
from backend.shared.config import load_settings
from backend.shared.db import Database
from backend.shared.files import FileStore
from backend.sim.executor import LocalExecutor
from backend.sim.expander import Expander
from backend.sim.results import ResultService
from backend.sim.scheduler import Scheduler
from backend.sim.service import TaskService

from scripts.seed_data import (
    ensure_metrics,
    ensure_quota,
    make_scenarios,
    make_set,
    make_sim_source,
    write_raw_manifests,
)


async def submit_and_run(
    tasks: TaskService,
    scheduler: Scheduler,
    principal: Principal,
    set_info: dict[str, Any],
    name: str,
    priority: int,
    max_rounds: int = 400,
) -> dict[str, Any]:
    runtime = RuntimeConfig(
        binary_id="log-resim",
        args=["--scenario", "${SCENARIO_URI}", "--out", "${OUTPUT_DIR}", "--seed", "${SEED}"],
        env={"SIM_SEED": str(20261112 + priority), "LOG_LEVEL": "info"},
        resource={"cpu": 1, "mem_gb": 1, "gpu": 0},
        timeout_sec=60,
        retry={"max": 1, "on": ["timeout", "worker_lost"]},
    )
    task = await tasks.submit(
        SimTaskCreate(
            name=name,
            set_id=set_info["set_id"],
            set_version=set_info["version"],
            runtime=runtime,
            priority=priority,
            batch={"max_cases": 0, "shard_size": 1000},
            metrics=["safety.brake.hard"],
            seed=20261112 + priority,
        ),
        principal,
    )
    for _ in range(max_rounds):
        await scheduler.step()
        await asyncio.sleep(0.12)
        current = await tasks.get(task["task_id"], principal)
        if current["status"] in {"succeeded", "failed", "canceled"}:
            return current
    return await tasks.get(task["task_id"], principal)


DEMO_TABLES = (
    "archive_export",
    "audit_log",
    "case_result",
    "case_run",
    "data_source",
    "metric_def",
    "metric_type",
    "outbox",
    "project_quota",
    "resource_reservation",
    "scenario",
    "scenario_metric",
    "scenario_set",
    "scenario_set_member",
    "scenario_set_version",
    "scenario_tag",
    "scenario_version",
    "sim_task",
    "tag",
    "task_control_request",
    "task_expand_cursor",
    "task_metric_agg",
    "task_summary",
    "worker",
)


async def reset_database(db: Database) -> None:
    tables = ", ".join(DEMO_TABLES)
    if db.is_postgres:
        await db.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    else:
        for table in DEMO_TABLES:
            await db.execute(f"DELETE FROM {table}")


async def seed_large(
    tasks: TaskService,
    expander: Expander,
    scenario_service: ScenarioService,
    set_service: SetService,
    source_ids: list[str],
    principal: Principal,
    large: int,
) -> None:
    extra = await make_scenarios(scenario_service, source_ids, principal, large, prefix="压力场景")
    big_set = await make_set(set_service, principal, f"万级展开集-{large}", extra, True)
    runtime = RuntimeConfig(
        binary_id="log-resim",
        args=["--scenario", "${SCENARIO_URI}", "--out", "${OUTPUT_DIR}"],
        env={"SIM_SEED": "42"},
        resource={"cpu": 1, "mem_gb": 1, "gpu": 0},
        timeout_sec=120,
    )
    task = await tasks.submit(
        SimTaskCreate(
            name="异步展开压测任务",
            set_id=big_set["set_id"],
            set_version=big_set["version"],
            runtime=runtime,
            priority=7,
            batch={"max_cases": 0, "shard_size": 1000},
            metrics=["safety.brake.hard"],
            seed=42,
        ),
        principal,
    )
    await expander.step()
    print(f"queued async task {task['task_id']} with {large} cases")


async def main_async(reset: bool, large: int) -> None:
    settings = load_settings()
    db = Database(settings.database_url)
    if reset:
        for name in ("scenarios", "sets", "sources", "outputs", "logs"):
            shutil.rmtree(settings.data_dir / name, ignore_errors=True)
        await reset_database(db)
    store = FileStore(settings.data_dir)
    scenario_service = ScenarioService(db, store)
    set_service = SetService(db, store)
    metric_service = MetricService(db)
    playback = PlaybackService(db, store)
    tasks = TaskService(db, set_service, sync_limit=settings.sync_expand_limit, store=store)
    results = ResultService(db, heartbeat_timeout_sec=settings.heartbeat_timeout_sec)
    expander = Expander(db, set_service, batch=settings.expand_batch)
    executor = LocalExecutor(db, results, settings)
    scheduler = Scheduler(db, settings, results, expander, executor)
    principal = Principal(user="seed", project="default", projects=("default",), admin=True)
    await ensure_quota(db)
    await ensure_metrics(metric_service, principal)
    uris = write_raw_manifests(settings.data_dir)
    source_ids = []
    for uri in uris:
        source = await playback.extract(
            ExtractRequest(uri=uri, format="json", project="default"), principal
        )
        await playback._build(source["source_id"])
        source_ids.append(source["source_id"])
    scenarios = await make_scenarios(scenario_service, source_ids, principal, 18)
    sets = []
    sets.append(await make_set(set_service, principal, "城市路口回归集", scenarios[:8], True))
    sets.append(await make_set(set_service, principal, "夜间与雨天集", scenarios[8:14], True))
    sets.append(await make_set(set_service, principal, "全量候选集", scenarios[14:18], False))
    await scheduler._ensure_worker()
    completed = []
    for index, set_info in enumerate(sets[:2]):
        task = await submit_and_run(tasks, scheduler, principal, set_info, f"回归任务-{index + 1}", 2 + index)
        completed.append(task)
    if completed:
        await make_sim_source(playback, settings.data_dir, principal, completed[0])
    if large > 0:
        await seed_large(tasks, expander, scenario_service, set_service, source_ids, principal, large)
    print(f"seed complete: {len(scenarios)} scenarios, {len(sets)} sets, {len(completed)} completed tasks")
    await scheduler.stop()
    await db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--large", type=int, default=0, help="add N scenarios for async expansion demo")
    args = parser.parse_args()
    asyncio.run(main_async(args.reset, args.large))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
