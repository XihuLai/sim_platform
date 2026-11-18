"""Scheduler-owned state transitions, worker reports and incremental aggregates."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.models import RuntimeConfig
from backend.scenario.common import loads
from backend.shared.canonical import utcnow
from backend.shared.db import Database, affected
from backend.sim.aggregate import ResultAggregateMixin
from backend.sim.status import retry_allowed


class ResultService(ResultAggregateMixin):
    def __init__(self, db: Database, heartbeat_timeout_sec: int = 30) -> None:
        self.db = db
        self.heartbeat_timeout_sec = heartbeat_timeout_sec

    # ------------------------------------------------------------- reports
    async def report_start(self, case_run_id: str, attempt: int, worker_id: str) -> bool:
        async with self.db.session() as session:
            case = await self._case_for_update(session, case_run_id)
            if (
                case is None
                or case["attempt"] != attempt
                or case["status"] not in {"scheduled", "queued"}
            ):
                await session.rollback()
                return False
            previous = case["status"]
            await session.execute(
                text(
                    """
                    UPDATE case_run SET status='running', started_at=COALESCE(started_at, now()),
                      heartbeat_at=now(), worker_id=:worker
                    WHERE id=:id AND attempt=:attempt
                    """
                ),
                {"id": case_run_id, "attempt": attempt, "worker": worker_id},
            )
            await self.bump(session, case["task_id"], {previous: -1, "running": 1})
            await self.refresh_task_status(session, case["task_id"])
            await session.commit()
            return True

    async def heartbeat(self, case_run_id: str, attempt: int, worker_id: str) -> bool:
        result = await self.db.execute(
            "UPDATE case_run SET heartbeat_at=now() WHERE id=:id AND attempt=:attempt "
            "AND worker_id=:worker AND status IN ('running','paused')",
            {"id": case_run_id, "attempt": attempt, "worker": worker_id},
        )
        return result > 0

    async def report_result(
        self,
        *,
        report_id: str,
        case_run_id: str,
        attempt: int,
        worker_id: str,
        status: str,
        metrics: dict[str, Any],
        exit_code: int | None = None,
        reason: str = "",
        output_uri: str = "",
    ) -> dict[str, Any]:
        if status not in {"succeeded", "failed", "canceled", "timeout", "worker_lost"}:
            return {"accepted": False, "code": "INVALID_STATUS"}
        async with self.db.session() as session:
            case = await self._case_for_update(session, case_run_id)
            if case is None:
                return {"accepted": False, "code": "NOT_FOUND"}
            if case["last_result_report_id"] == report_id:
                return {"accepted": True, "code": "DUPLICATE", "status": case["status"]}
            if case["status"] not in {"running", "paused"} or case["attempt"] != attempt or case["worker_id"] != worker_id:
                return {"accepted": False, "code": "STALE", "status": case["status"]}
            task = await self._task(session, case["task_id"])
            runtime = RuntimeConfig.model_validate(loads(task["runtime_config"]))
            retry = retry_allowed(status, attempt, runtime.retry.max, runtime.retry.on)
            if retry:
                return await self._retry_case(session, case, case_run_id, attempt, report_id, status)
            return await self._commit_case(
                session, case, case_run_id, attempt, report_id, status, metrics, exit_code, reason, output_uri
            )

    async def _retry_case(
        self,
        session: AsyncSession,
        case: dict[str, Any],
        case_run_id: str,
        attempt: int,
        report_id: str,
        status: str,
    ) -> dict[str, Any]:
        await session.execute(
            text(
                "UPDATE case_run SET status='queued', attempt=attempt+1, worker_id=NULL, "
                "heartbeat_at=NULL, started_at=NULL, finished_at=NULL, reason=:reason, "
                "last_result_report_id=:report WHERE id=:id AND attempt=:attempt"
            ),
            {"id": case_run_id, "attempt": attempt, "reason": status, "report": report_id},
        )
        await self.bump(session, case["task_id"], {case["status"]: -1, "queued": 1})
        await self._release(session, case_run_id, attempt)
        await self.refresh_task_status(session, case["task_id"])
        await session.commit()
        return {"accepted": True, "code": "RETRY", "status": "queued", "attempt": attempt + 1}

    async def _commit_case(
        self,
        session: AsyncSession,
        case: dict[str, Any],
        case_run_id: str,
        attempt: int,
        report_id: str,
        status: str,
        metrics: dict[str, Any],
        exit_code: int | None,
        reason: str,
        output_uri: str,
    ) -> dict[str, Any]:
        await session.execute(
            text(
                """
                UPDATE case_run SET status=:status, exit_code=:exit_code, reason=:reason,
                  output_uri=:output_uri, finished_at=now(), last_result_report_id=:report,
                  heartbeat_at=now()
                WHERE id=:id AND attempt=:attempt
                """
            ),
            {
                "id": case_run_id,
                "attempt": attempt,
                "status": status,
                "exit_code": exit_code,
                "reason": reason,
                "output_uri": output_uri,
                "report": report_id,
            },
        )
        await self.bump(session, case["task_id"], {case["status"]: -1, status: 1})
        await self._write_results(session, case, attempt, metrics, output_uri)
        await self._bump_passed(session, case["task_id"], status, metrics)
        await self._release(session, case_run_id, attempt)
        await self.refresh_task_status(session, case["task_id"])
        await session.commit()
        return {"accepted": True, "code": "COMMITTED", "status": status}

    # ---------------------------------------------------------- lifecycle
    async def recover_heartbeats(self) -> int:
        cutoff = utcnow() - timedelta(seconds=self.heartbeat_timeout_sec)
        rows = await self.db.fetch_all(
            "SELECT id, task_id, attempt, status, started_at FROM case_run "
            "WHERE status IN ('scheduled','running','paused') "
            "AND (heartbeat_at IS NULL OR heartbeat_at < :cutoff) LIMIT 200",
            {"cutoff": cutoff},
        )
        lost = 0
        for row in rows:
            task = await self.db.fetch_one(
                "SELECT runtime_config FROM sim_task WHERE id=:tid", {"tid": row["task_id"]}
            )
            if task is None:
                continue
            runtime = RuntimeConfig.model_validate(loads(task["runtime_config"]))
            reason = self._loss_reason(row, runtime.timeout_sec)
            result = await self._lose(row, reason, runtime)
            if result:
                lost += 1
        return lost

    async def _lose(self, row: dict[str, Any], reason: str, runtime: RuntimeConfig) -> bool:
        async with self.db.session() as session:
            case = await self._case_for_update(session, row["id"])
            if (
                case is None
                or case["attempt"] != row["attempt"]
                or case["status"] not in {"scheduled", "running", "paused"}
            ):
                return False
            retry = retry_allowed(reason, case["attempt"], runtime.retry.max, runtime.retry.on)
            if retry:
                await session.execute(
                    text(
                        "UPDATE case_run SET status='queued', attempt=attempt+1, worker_id=NULL, "
                        "heartbeat_at=NULL, started_at=NULL, finished_at=NULL, reason=:reason "
                        "WHERE id=:id AND attempt=:attempt"
                    ),
                    {"id": case["id"], "attempt": case["attempt"], "reason": reason},
                )
                await self.bump(session, case["task_id"], {case["status"]: -1, "queued": 1})
            else:
                await session.execute(
                    text(
                        "UPDATE case_run SET status=:reason, finished_at=now(), worker_id=NULL, "
                        "reason=:reason WHERE id=:id AND attempt=:attempt"
                    ),
                    {"id": case["id"], "attempt": case["attempt"], "reason": reason},
                )
                await self.bump(session, case["task_id"], {case["status"]: -1, reason: 1})
            await self._release(session, case["id"], case["attempt"])
            await self.refresh_task_status(session, case["task_id"])
            await session.commit()
            return True

    async def cancel_active(self, task_id: str, reason: str = "user_cancel") -> int:
        rows = await self.db.fetch_all(
            "SELECT id, status, attempt FROM case_run WHERE task_id=:tid AND status IN "
            "('queued','scheduled','running','paused')",
            {"tid": task_id},
        )
        canceled = 0
        for row in rows:
            async with self.db.session() as session:
                result = await session.execute(
                    text(
                        "UPDATE case_run SET status='canceled', reason=:reason, finished_at=now() "
                        "WHERE id=:id AND attempt=:attempt AND status=:old"
                    ),
                    {"id": row["id"], "attempt": row["attempt"], "old": row["status"], "reason": reason},
                )
                if affected(result):
                    await self.bump(session, task_id, {row["status"]: -1, "canceled": 1})
                    await self._release(session, row["id"], row["attempt"])
                    canceled += 1
                await session.commit()
        async with self.db.session() as session:
            await self.refresh_task_status(session, task_id)
            await session.commit()
        return canceled

    async def pause_active(self, task_id: str) -> int:
        rows = await self.db.fetch_all(
            "SELECT id, status, attempt FROM case_run WHERE task_id=:tid AND status IN ('scheduled','running')",
            {"tid": task_id},
        )
        paused = 0
        for row in rows:
            async with self.db.session() as session:
                result = await session.execute(
                    text("UPDATE case_run SET status='paused' WHERE id=:id AND attempt=:attempt AND status=:old"),
                    {"id": row["id"], "attempt": row["attempt"], "old": row["status"]},
                )
                if affected(result):
                    await self.bump(session, task_id, {row["status"]: -1, "paused": 1})
                    paused += 1
                await session.commit()
        return paused

    async def resume_active(self, task_id: str) -> int:
        rows = await self.db.fetch_all(
            "SELECT id, attempt, started_at FROM case_run WHERE task_id=:tid AND status='paused'",
            {"tid": task_id},
        )
        resumed = 0
        for row in rows:
            target = "running" if row["started_at"] is not None else "queued"
            async with self.db.session() as session:
                result = await session.execute(
                    text(
                        "UPDATE case_run SET status=:target, worker_id=CASE WHEN :target='queued' "
                        "THEN NULL ELSE worker_id END WHERE id=:id AND attempt=:attempt AND status='paused'"
                    ),
                    {"id": row["id"], "attempt": row["attempt"], "target": target},
                )
                if affected(result):
                    await self.bump(session, task_id, {"paused": -1, target: 1})
                    resumed += 1
                await session.commit()
        return resumed

    # --------------------------------------------------------- aggregation

    def _loss_reason(self, row: dict[str, Any], timeout_sec: int) -> str:
        started = row.get("started_at")
        if isinstance(started, datetime):
            elapsed = (utcnow() - started).total_seconds()
            if elapsed > timeout_sec:
                return "timeout"
        return "worker_lost"
