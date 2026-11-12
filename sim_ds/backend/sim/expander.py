"""Async expansion worker: idempotent batches, fixed partition timestamp, cursor."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.domain.models import RuntimeConfig
from backend.scenario.common import loads
from backend.scenario.sets import SetService
from backend.shared.auth import Principal
from backend.shared.canonical import sha256_text, utcnow
from backend.shared.db import Database, affected, dumps
from backend.sim.status import counts_from_row, derive_task_status


class Expander:
    def __init__(self, db: Database, sets: SetService, batch: int = 1000) -> None:
        self.db = db
        self.sets = sets
        self.batch = batch

    async def step(self) -> int:
        tasks = await self.db.fetch_all(
            "SELECT * FROM sim_task WHERE status='expanding' ORDER BY created_at LIMIT 5"
        )
        expanded = 0
        for task in tasks:
            expanded += await self._expand_task(task)
        return expanded

    async def _expand_task(self, task: dict[str, Any]) -> int:
        cursor = await self.db.fetch_one(
            "SELECT * FROM task_expand_cursor WHERE task_id=:tid", {"tid": task["id"]}
        )
        if cursor is None:
            await self._fail(task["id"], "缺少展开游标")
            return 0
        if await self._cancel_requested(task["id"]):
            await self._finish_cancelled(task["id"])
            return 0
        principal = Principal(
            user="scheduler", project=task["project"], projects=(task["project"],), admin=True
        )
        try:
            snapshot = await self.sets.load_snapshot(
                task["set_id"], task["set_version"], principal, require_frozen=True
            )
        except Exception as exc:  # snapshot unavailable must fail the task
            await self._fail(task["id"], f"场景集快照不可用：{exc}")
            return 0
        members = snapshot["members"]
        runtime = RuntimeConfig.model_validate(loads(task["runtime_config"]))
        max_cases = self._max_cases(task)
        expected = len(members) if not max_cases else min(len(members), max_cases)
        if expected <= 0:
            await self._fail(task["id"], "场景集为空")
            return 0
        start = int(cursor["last_offset"])
        if start >= expected:
            await self._finalize(task, expected, cursor)
            return 0
        chunk = members[start : min(start + self.batch, expected)]
        inserted = await self._insert_batch(task, cursor, chunk, runtime)
        await self._advance(task["id"], start + len(chunk), inserted, expected, cursor)
        if start + len(chunk) >= expected:
            await self._finalize(task, expected, cursor)
        return inserted

    async def _insert_batch(
        self,
        task: dict[str, Any],
        cursor: dict[str, Any],
        chunk: list[dict[str, Any]],
        runtime: RuntimeConfig,
    ) -> int:
        created_at = cursor["case_run_created_at"]
        inserted = 0
        async with self.db.session() as session:
            for member in chunk:
                case_id = "run_" + sha256_text(f"{task['id']}:{member['scenario_id']}")[7:31]
                result = await session.execute(
                    text(
                        """
                        INSERT INTO case_run(id,task_id,scenario_id,scenario_version,priority,effective_priority,
                          status,attempt,resource_req,waiting_since,created_at)
                        VALUES (:id,:tid,:scn,:sver,:priority,:priority,'queued',0,
                          CAST(:resource AS JSONB),:created_at,:created_at)
                        ON CONFLICT (task_id,scenario_id,created_at) DO NOTHING
                        """
                    ),
                    {
                        "id": case_id,
                        "tid": task["id"],
                        "scn": member["scenario_id"],
                        "sver": member["scenario_version"],
                        "priority": task["priority"],
                        "resource": dumps(runtime.resource.model_dump()),
                        "created_at": created_at,
                    },
                )
                inserted += affected(result)
            await session.commit()
        return inserted

    async def _advance(
        self,
        task_id: str,
        offset: int,
        inserted: int,
        expected: int,
        cursor: dict[str, Any],
    ) -> None:
        async with self.db.session() as session:
            await session.execute(
                text(
                    "UPDATE task_expand_cursor SET last_offset=:offset, updated_at=now() WHERE task_id=:tid"
                ),
                {"tid": task_id, "offset": offset},
            )
            await session.execute(
                text(
                    """
                    UPDATE task_summary ts SET total=:expected,
                      queued=agg.queued, scheduled=agg.scheduled, running=agg.running,
                      succeeded=agg.succeeded, failed=agg.failed, canceled=agg.canceled,
                      timeout=agg.timeout, worker_lost=agg.worker_lost, updated_at=now()
                    FROM (
                      SELECT COUNT(*) FILTER (WHERE status='queued') AS queued,
                             COUNT(*) FILTER (WHERE status='scheduled') AS scheduled,
                             COUNT(*) FILTER (WHERE status='running') AS running,
                             COUNT(*) FILTER (WHERE status='succeeded') AS succeeded,
                             COUNT(*) FILTER (WHERE status='failed') AS failed,
                             COUNT(*) FILTER (WHERE status='canceled') AS canceled,
                             COUNT(*) FILTER (WHERE status='timeout') AS timeout,
                             COUNT(*) FILTER (WHERE status='worker_lost') AS worker_lost
                      FROM case_run WHERE task_id=:tid
                    ) agg
                    WHERE ts.task_id=:tid
                    """
                ),
                {"tid": task_id, "expected": expected},
            )
            await session.commit()

    async def _finalize(self, task: dict[str, Any], expected: int, cursor: dict[str, Any]) -> None:
        count_row = await self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM case_run WHERE task_id=:tid AND created_at=:ct",
            {"tid": task["id"], "ct": cursor["case_run_created_at"]},
        )
        actual = int(count_row["n"]) if count_row else 0
        if actual != expected:
            await self._fail(task["id"], f"展开数量不匹配：预期 {expected}，实际 {actual}")
            return
        summary = await self.db.fetch_one("SELECT * FROM task_summary WHERE task_id=:tid", {"tid": task["id"]})
        counts = counts_from_row(summary)
        cancel = await self._cancel_requested(task["id"])
        status = derive_task_status(
            counts, total=expected, expanding=False, cancel_accepted=cancel, pause_accepted=False
        )
        async with self.db.session() as session:
            await session.execute(
                text("UPDATE sim_task SET total_cases=:total, status=:status WHERE id=:tid"),
                {"tid": task["id"], "total": expected, "status": status},
            )
            await session.execute(
                text("UPDATE task_summary SET total=:total, updated_at=now() WHERE task_id=:tid"),
                {"tid": task["id"], "total": expected},
            )
            await session.commit()

    async def _finish_cancelled(self, task_id: str) -> None:
        active = await self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM case_run WHERE task_id=:tid AND status IN "
            "('queued','scheduled','running','paused')",
            {"tid": task_id},
        )
        if active and int(active["n"]) == 0:
            await self.db.execute(
                "UPDATE sim_task SET status='canceled', finished_at=now() WHERE id=:tid AND status='expanding'",
                {"tid": task_id},
            )

    async def _fail(self, task_id: str, reason: str) -> None:
        await self.db.execute(
            "UPDATE sim_task SET status='failed', finished_at=now() WHERE id=:tid AND status='expanding'",
            {"tid": task_id},
        )
        await self.db.execute(
            "UPDATE task_summary SET updated_at=now() WHERE task_id=:tid", {"tid": task_id}
        )
        await self.db.execute(
            "INSERT INTO audit_log(actor,project,action,resource_type,resource_id,detail) "
            "SELECT 'scheduler', project, 'task.expand_failed', 'sim_task', id, CAST(:detail AS JSONB) "
            "FROM sim_task WHERE id=:tid",
            {"tid": task_id, "detail": dumps({"reason": reason, "at": utcnow().isoformat()})},
        )

    async def _cancel_requested(self, task_id: str) -> bool:
        row = await self.db.fetch_one(
            "SELECT 1 FROM task_control_request WHERE task_id=:tid AND command='cancel' "
            "AND status IN ('pending','processing','completed') LIMIT 1",
            {"tid": task_id},
        )
        return row is not None

    def _max_cases(self, task: dict[str, Any]) -> int:
        batch = loads(task.get("batch") or {})
        return int(batch.get("max_cases", 0)) if isinstance(batch, dict) else 0
