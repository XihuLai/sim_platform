from pathlib import Path

from backend.shared.auth import Principal
from backend.shared.db import Database
from backend.tests.helpers import runtime, task_payload
from backend.tests.test_task_sync import build_services, run_task

MOCK_KEYS = {
    "safe.collision.rate",
    "safe.ttc.min",
    "comfort.jerk.p95",
    "compliance.speed",
    "efficiency.route_done",
}


async def test_mock_runner_executes_and_feeds_failure_views(
    db: Database, tmp_path: Path, principal: Principal
) -> None:
    tasks, scheduler = await build_services(db, tmp_path, principal)
    set_row = await db.fetch_one("SELECT id, current_version FROM scenario_set LIMIT 1")
    payload = task_payload({"set_id": set_row["id"], "version": set_row["current_version"]})
    payload.runtime = runtime().model_copy(update={"binary_id": "mock"})
    payload.seed = 7
    submitted = await tasks.submit(payload, principal)
    final = await run_task(tasks, scheduler, submitted["task_id"], principal)
    assert final["status"] in {"succeeded", "failed"}

    cases = await tasks.cases(submitted["task_id"], principal)
    assert len(cases["items"]) == 1
    case = cases["items"][0]
    if case["status"] == "succeeded":
        assert case["metrics"] and set(case["metrics"]) <= MOCK_KEYS
    else:
        assert case["metrics"] == {}

    summary = await tasks.summary(submitted["task_id"], principal)
    failed = await tasks.cases(submitted["task_id"], principal, outcome="fail")
    assert len(summary["failures"]) == final["fail_count"]
    assert len(failed["items"]) == final["fail_count"]
