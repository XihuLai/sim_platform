"""Scheduler-owned dispatch and report endpoints used by remote workers."""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import text

from backend.scenario.common import loads
from backend.shared.config import Settings
from backend.shared.db import Database, affected, dumps
from backend.shared.errors import AppError
from backend.sim.results import ResultService


class WorkerService:
    def __init__(
        self, db: Database, results: ResultService, settings: Settings
    ) -> None:
        self.db = db
        self.results = results
        self.settings = settings

    def authenticate(self, authorization: str | None) -> bool:
        scheme, _, token = (authorization or "").partition(" ")
        return (
            scheme.lower() == "bearer"
            and bool(self.settings.worker_token)
            and secrets.compare_digest(token, self.settings.worker_token)
        )

    async def claim(
        self, worker_id: str, capacity: dict[str, int] | None = None
    ) -> dict[str, Any] | None:
        if not worker_id or len(worker_id) > 128:
            raise AppError("INVALID_WORKER_ID", "worker_id 长度必须为 1 到 128", status=422)
        async with self.db.session() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT o.id AS outbox_id, c.*, t.runtime_config, t.seed,
                               v.file_uri AS scenario_uri, v.file_checksum AS scenario_checksum
                        FROM outbox o
                        JOIN case_run c ON c.id=o.case_run_id
                        JOIN sim_task t ON t.id=c.task_id
                        JOIN scenario_version v
                          ON v.scenario_id=c.scenario_id AND v.version=c.scenario_version
                        WHERE o.published=false AND o.payload->>'event'='dispatch'
                          AND c.status='scheduled'
                          AND o.payload->>'attempt'=c.attempt::text
                        ORDER BY o.id
                        LIMIT 1
                        FOR UPDATE OF o, c SKIP LOCKED
                        """
                    )
                )
            ).mappings().first()
            if row is None:
                await session.commit()
                return None
            runtime = loads(row["runtime_config"])
            if (
                not str(row["scenario_uri"]).startswith("s3://")
                or not str(runtime.get("binary_uri", "")).startswith("s3://")
                or not runtime.get("binary_checksum")
            ):
                raise AppError(
                    "WORKER_INPUT_NOT_PUBLISHED",
                    "Worker 输入必须先发布到对象存储并提供 Binary SHA-256",
                    status=409,
                    detail={"case_run_id": row["id"], "attempt": row["attempt"]},
                )
            claimed = await session.execute(
                text("UPDATE outbox SET published=true WHERE id=:id AND published=false"),
                {"id": row["outbox_id"]},
            )
            if not affected(claimed):
                await session.rollback()
                return None
            updated = await session.execute(
                text(
                    "UPDATE case_run SET worker_id=:worker, heartbeat_at=now() "
                    "WHERE id=:id AND attempt=:attempt AND status='scheduled'"
                ),
                {"worker": worker_id, "id": row["id"], "attempt": row["attempt"]},
            )
            if not affected(updated):
                await session.rollback()
                return None
            effective_capacity = capacity or {
                "cpu": self.settings.k8s_slot_cpu * self.settings.k8s_worker_slots,
                "mem_gb": self.settings.k8s_slot_mem_gb * self.settings.k8s_worker_slots,
                "gpu": self.settings.k8s_slot_gpu * self.settings.k8s_worker_slots,
            }
            await session.execute(
                text(
                    """
                    INSERT INTO worker(id,executor_type,status,capacity,used,heartbeat_at,started_at)
                    VALUES (:id,'k8s_pool','online',CAST(:capacity AS JSONB),'{}',now(),now())
                    ON CONFLICT (id) DO UPDATE SET status='online', heartbeat_at=now()
                    """
                ),
                {"id": worker_id, "capacity": dumps(effective_capacity)},
            )
            await session.commit()
        return {
            "case_run_id": row["id"],
            "task_id": row["task_id"],
            "scenario_id": row["scenario_id"],
            "scenario_version": row["scenario_version"],
            "attempt": row["attempt"],
            "priority": row["priority"],
            "worker_id": worker_id,
            "runtime": runtime,
            "seed": row["seed"],
            "scenario_uri": row["scenario_uri"],
            "scenario_checksum": row["scenario_checksum"],
        }

    async def start(self, case_run_id: str, attempt: int, worker_id: str) -> bool:
        await self.db.execute(
            """
            INSERT INTO worker(id,executor_type,status,capacity,used,heartbeat_at,started_at)
            VALUES (:id,'k8s','online',CAST(:capacity AS JSONB),'{}',now(),now())
            ON CONFLICT (id) DO UPDATE SET status='online', heartbeat_at=now()
            """,
            {
                "id": worker_id,
                "capacity": dumps(
                    {
                        "cpu": self.settings.k8s_slot_cpu * self.settings.k8s_worker_slots,
                        "mem_gb": self.settings.k8s_slot_mem_gb * self.settings.k8s_worker_slots,
                        "gpu": self.settings.k8s_slot_gpu * self.settings.k8s_worker_slots,
                    }
                ),
            },
        )
        return await self.results.report_start(case_run_id, attempt, worker_id)

    async def heartbeat(self, case_run_id: str, attempt: int, worker_id: str) -> dict[str, Any]:
        accepted = await self.results.heartbeat(case_run_id, attempt, worker_id)
        row = await self.db.fetch_one(
            "SELECT status, attempt, worker_id FROM case_run "
            "WHERE id=:id ORDER BY created_at DESC LIMIT 1",
            {"id": case_run_id},
        )
        if row is None:
            return {"accepted": False, "action": "stop"}
        if not accepted or row["attempt"] != attempt or row["worker_id"] != worker_id:
            return {"accepted": False, "action": "stop"}
        await self.db.execute(
            "UPDATE worker SET status='online', heartbeat_at=now() WHERE id=:id",
            {"id": worker_id},
        )
        action = {"paused": "pause", "canceled": "cancel"}.get(row["status"], "continue")
        return {"accepted": True, "action": action}

    async def report(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self.results.report_result(**body)
