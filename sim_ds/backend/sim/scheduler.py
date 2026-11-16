"""Single-leader scheduler: control replay, quota-safe claims, outbox dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from sqlalchemy import text

from backend.scenario.common import loads
from backend.shared.config import Settings
from backend.shared.db import Database, affected, dumps
from backend.sim.executor import LocalExecutor
from backend.sim.expander import Expander
from backend.sim.results import ResultService

LOG = logging.getLogger("sim.scheduler")
ADVISORY_KEY = 7_311_004


class Scheduler:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        results: ResultService,
        expander: Expander,
        executor: LocalExecutor,
    ) -> None:
        self.db = db
        self.settings = settings
        self.results = results
        self.expander = expander
        self.executor = executor
        self._stop = asyncio.Event()
        self._lock_conn: Any = None
        self._leader = False
        self._loop_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not self.db.is_postgres:
            raise RuntimeError("scheduler requires PostgreSQL; SQLite is development-only")
        await self._ensure_worker()
        self._loop_task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        self._stop.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            self._loop_task = None
        if self._lock_conn is not None:
            with contextlib.suppress(Exception):
                await self._lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_KEY})
                await self._lock_conn.close()
            self._lock_conn = None
        for task in list(self.executor.tasks):
            task.cancel()
        for process in list(self.executor.processes.values()):
            with contextlib.suppress(ProcessLookupError):
                process.kill()

    async def run_forever(self) -> None:
        last_reconcile = 0.0
        while not self._stop.is_set():
            try:
                if not self._leader and not await self._try_leader():
                    await asyncio.sleep(max(1.0, self.settings.scheduler_tick_sec))
                    continue
                await self.step()
                now = asyncio.get_running_loop().time()
                if now - last_reconcile >= self.settings.reconcile_sec:
                    last_reconcile = now
                    await self.results.reconcile()
                    await self.results.recompute_p95()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOG.exception("scheduler tick failed")
            await asyncio.sleep(self.settings.scheduler_tick_sec)

    async def step(self) -> None:
        await self.results.recover_heartbeats()
        await self.process_controls()
        await self.expander.step()
        await self.claim()
        await self.dispatch_outbox()

    async def _try_leader(self) -> bool:
        if self._lock_conn is None:
            self._lock_conn = await self.db.engine.connect()
        result = await self._lock_conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_KEY})
        self._leader = bool(result.scalar())
        return self._leader

    async def _ensure_worker(self) -> None:
        capacity = dumps(
            {"cpu": self.settings.worker_cpu, "mem_gb": self.settings.worker_mem_gb, "gpu": self.settings.worker_gpu}
        )
        await self.db.execute(
            """
            INSERT INTO worker(id,executor_type,status,capacity,used,heartbeat_at,started_at)
            VALUES (:id,'local','online',CAST(:capacity AS JSONB),'{}',now(),now())
            ON CONFLICT (id) DO UPDATE SET capacity=EXCLUDED.capacity, status='online', heartbeat_at=now()
            """,
            {"id": self.settings.worker_id, "capacity": capacity},
        )

    # ----------------------------------------------------------- controls
    async def process_controls(self) -> int:
        claimed = await self.db.fetch_all(
            """
            UPDATE task_control_request SET status='processing'
            WHERE request_id IN (
              SELECT request_id FROM task_control_request
              WHERE status IN ('pending','processing')
              ORDER BY created_at LIMIT 10 FOR UPDATE SKIP LOCKED
            ) RETURNING *
            """
        )
        for request in claimed:
            await self._apply_control(request)
        return len(claimed)

    async def _apply_control(self, request: dict[str, Any]) -> None:
        task = await self.db.fetch_one("SELECT * FROM sim_task WHERE id=:id", {"id": request["task_id"]})
        code = "APPLIED"
        detail: dict[str, Any] = {}
        if task is None:
            code = "TASK_MISSING"
        elif request["command"] == "pause":
            code, detail = await self._pause(task)
        elif request["command"] == "resume":
            code, detail = await self._resume(task)
        elif request["command"] == "cancel":
            code, detail = await self._cancel(task)
        await self.db.execute(
            """
            UPDATE task_control_request SET status='completed', result_code=:code,
              result_detail=CAST(:detail AS JSONB), completed_at=now()
            WHERE request_id=:rid
            """,
            {"rid": request["request_id"], "code": code, "detail": dumps(detail)},
        )

    async def _pause(self, task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if task["status"] in {"expanding", "succeeded", "failed", "canceled"}:
            return "REJECTED_STATE", {"status": task["status"]}
        running = await self.db.fetch_all(
            "SELECT id, status FROM case_run WHERE task_id=:tid AND status IN ('scheduled','running')",
            {"tid": task["id"]},
        )
        if any(row["status"] == "running" for row in running):
            for row in running:
                await self.executor.pause(row["id"])
        paused = await self.results.pause_active(task["id"])
        async with self.db.session() as session:
            await self.results.refresh_task_status(session, task["id"])
            await session.commit()
        return "PAUSED", {"paused_cases": paused}

    async def _resume(self, task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if task["status"] != "paused":
            return "REJECTED_STATE", {"status": task["status"]}
        paused = await self.db.fetch_all(
            "SELECT id, started_at FROM case_run WHERE task_id=:tid AND status='paused'", {"tid": task["id"]}
        )
        for row in paused:
            await self.executor.resume(row["id"])
        resumed = await self.results.resume_active(task["id"])
        async with self.db.session() as session:
            await self.results.refresh_task_status(session, task["id"])
            await session.commit()
        return "RESUMED", {"resumed_cases": resumed}

    async def _cancel(self, task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        cases = await self.db.fetch_all(
            "SELECT id FROM case_run WHERE task_id=:tid AND status IN ('queued','scheduled','running','paused')",
            {"tid": task["id"]},
        )
        for row in cases:
            await self.executor.cancel(row["id"])
        canceled = await self.results.cancel_active(task["id"])
        async with self.db.session() as session:
            await self.results.refresh_task_status(session, task["id"])
            await session.commit()
        return "CANCELED", {"canceled_cases": canceled}

    # --------------------------------------------------------------- claim
    async def claim(self) -> int:
        rows = await self.db.fetch_all(
            CLAIM_SQL,
            {
                "worker": self.settings.worker_id,
                "aging": self.settings.aging_sec,
                "batch": self.settings.scheduler_batch,
            },
        )
        if not rows:
            return 0
        async with self.db.session() as session:
            task_ids: set[str] = set()
            for row in rows:
                if await self._reserve(session, row):
                    task_ids.add(row["task_id"])
            for task_id in task_ids:
                await self.results.refresh_task_status(session, task_id)
            await session.commit()
        return len(rows)

    async def _reserve(self, session: Any, row: dict[str, Any]) -> bool:
        resource = loads(row["resource_req"]) or {}
        moved = await session.execute(
            text(
                "UPDATE case_run SET status='scheduled', worker_id=:worker, heartbeat_at=now() "
                "WHERE id=:id AND attempt=:attempt AND status='queued'"
            ),
            {"id": row["id"], "attempt": row["attempt"], "worker": self.settings.worker_id},
        )
        if not affected(moved):
            return False
        await self.results.bump(session, row["task_id"], {"queued": -1, "scheduled": 1})
        await session.execute(
            text(
                """
                INSERT INTO resource_reservation(case_run_id,attempt,project,worker_id,owner,cpu,mem_gb,gpu)
                SELECT :cid,:attempt,t.project,:worker,t.owner,:cpu,:mem,:gpu
                FROM sim_task t WHERE t.id=:tid
                ON CONFLICT (case_run_id,attempt) DO UPDATE SET released_at=NULL, created_at=now()
                """
            ),
            {
                "cid": row["id"],
                "attempt": row["attempt"],
                "worker": self.settings.worker_id,
                "tid": row["task_id"],
                "cpu": int(resource.get("cpu", 0)),
                "mem": int(resource.get("mem_gb", 0)),
                "gpu": int(resource.get("gpu", 0)),
            },
        )
        await session.execute(
            text("INSERT INTO outbox(case_run_id,payload) VALUES (:cid,CAST(:payload AS JSONB))"),
            {
                "cid": row["id"],
                "payload": dumps(
                    {"task_id": row["task_id"], "attempt": row["attempt"], "event": "dispatch"}
                ),
            },
        )
        return True

    # ------------------------------------------------------------ dispatch
    async def dispatch_outbox(self) -> int:
        rows = await self.db.fetch_all(
            """
            SELECT o.id AS outbox_id, c.id, c.task_id, c.scenario_id, c.scenario_version, c.attempt
            FROM outbox o
            JOIN case_run c ON c.id=o.case_run_id
            WHERE o.published=false AND c.status='scheduled'
            ORDER BY o.id LIMIT 100
            """
        )
        dispatched = 0
        for row in rows:
            await self.executor.submit(row)
            await self.db.execute("UPDATE outbox SET published=true WHERE id=:id", {"id": row["outbox_id"]})
            dispatched += 1
        return dispatched


CLAIM_SQL = """
WITH active AS (
  SELECT project, COUNT(*) AS cnt, COALESCE(SUM(cpu),0) AS cpu,
         COALESCE(SUM(mem_gb),0) AS mem, COALESCE(SUM(gpu),0) AS gpu
  FROM resource_reservation WHERE released_at IS NULL GROUP BY project
), wactive AS (
  SELECT worker_id, COALESCE(SUM(cpu),0) AS cpu, COALESCE(SUM(mem_gb),0) AS mem,
         COALESCE(SUM(gpu),0) AS gpu
  FROM resource_reservation WHERE released_at IS NULL GROUP BY worker_id
)
SELECT c.id, c.task_id, c.scenario_id, c.scenario_version, c.attempt, c.resource_req
FROM case_run c
JOIN sim_task t ON t.id=c.task_id
JOIN worker w ON w.id=:worker AND w.status='online'
LEFT JOIN project_quota q ON q.project=t.project
LEFT JOIN active a ON a.project=t.project
LEFT JOIN wactive wa ON wa.worker_id=w.id
WHERE c.status='queued' AND t.status IN ('queued','scheduled','running')
  AND NOT EXISTS (
    SELECT 1 FROM task_control_request r WHERE r.task_id=t.id AND r.command='pause'
      AND r.status IN ('pending','processing')
  )
  AND (q.max_running_cases IS NULL OR COALESCE(a.cnt,0) < q.max_running_cases)
  AND (c.priority <= 2 OR q.max_running_cases IS NULL OR q.reserved_high_priority IS NULL
       OR COALESCE(a.cnt,0) < q.max_running_cases - q.reserved_high_priority)
  AND (q.max_cpu IS NULL OR COALESCE(a.cpu,0) + (c.resource_req->>'cpu')::int <= q.max_cpu)
  AND (q.max_mem_gb IS NULL OR COALESCE(a.mem,0) + (c.resource_req->>'mem_gb')::int <= q.max_mem_gb)
  AND (q.max_gpu IS NULL OR COALESCE(a.gpu,0) + (c.resource_req->>'gpu')::int <= q.max_gpu)
  AND ((w.capacity->>'cpu')::int >= COALESCE(wa.cpu,0) + (c.resource_req->>'cpu')::int)
  AND ((w.capacity->>'mem_gb')::int >= COALESCE(wa.mem,0) + (c.resource_req->>'mem_gb')::int)
  AND ((w.capacity->>'gpu')::int >= COALESCE(wa.gpu,0) + (c.resource_req->>'gpu')::int)
ORDER BY GREATEST(0, c.priority - FLOOR(EXTRACT(EPOCH FROM now()-c.waiting_since)/:aging)),
         c.waiting_since
LIMIT :batch
FOR UPDATE OF c SKIP LOCKED
"""
