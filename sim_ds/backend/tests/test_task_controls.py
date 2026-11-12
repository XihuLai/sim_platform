from pathlib import Path

from backend.shared.auth import Principal
from backend.shared.db import Database
from backend.tests.helpers import task_payload
from backend.tests.test_task_sync import build_services


async def test_pause_resume_cancel_are_idempotent(db: Database, tmp_path: Path, principal: Principal) -> None:
    tasks, scheduler = await build_services(db, tmp_path, principal)
    set_row = await db.fetch_one("SELECT id, current_version FROM scenario_set LIMIT 1")
    task = await tasks.submit(
        task_payload({"set_id": set_row["id"], "version": set_row["current_version"]}), principal
    )
    task_id = task["task_id"]

    paused = await tasks.control(task_id, "pause", "req-pause", principal)
    assert paused["accepted"] is True
    await scheduler.step()
    assert (await tasks.get(task_id, principal))["status"] == "paused"
    replay = await tasks.control(task_id, "pause", "req-pause", principal)
    assert replay["request_id"] == "req-pause"

    await tasks.control(task_id, "resume", "req-resume", principal)
    await scheduler.process_controls()
    assert (await tasks.get(task_id, principal))["status"] == "queued"

    await tasks.control(task_id, "cancel", "req-cancel", principal)
    await scheduler.step()
    final = await tasks.get(task_id, principal)
    assert final["status"] == "canceled"
    rows = await db.fetch_all("SELECT status FROM case_run WHERE task_id=:tid", {"tid": task_id})
    assert rows and all(row["status"] == "canceled" for row in rows)
    requests = await db.fetch_all(
        "SELECT request_id, status FROM task_control_request WHERE task_id=:tid ORDER BY created_at",
        {"tid": task_id},
    )
    assert [row["request_id"] for row in requests] == ["req-pause", "req-resume", "req-cancel"]
    assert all(row["status"] == "completed" for row in requests)
