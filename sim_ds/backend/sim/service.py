"""Task submission, read models, control requests and queue statistics."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.models import SimTaskCreate
from backend.scenario.sets import SetService
from backend.shared.auth import Principal, audit
from backend.shared.canonical import sha256_text, utcnow
from backend.shared.db import Database, dumps
from backend.shared.errors import AppError, conflict, not_found
from backend.shared.files import FileStore
from backend.sim.fingerprint import compute_fingerprint, engine_digest
from backend.sim.read_models import TaskReadMixin


class TaskService(TaskReadMixin):
    def __init__(
        self, db: Database, sets: SetService, sync_limit: int = 500, store: FileStore | None = None
    ) -> None:
        self.db = db
        self.sets = sets
        self.sync_limit = sync_limit
        self.store = store

    # ------------------------------------------------------------- submit
    async def submit(self, payload: SimTaskCreate, principal: Principal) -> dict[str, Any]:
        project = self._scope_project(payload.project or principal.project, principal)
        if payload.priority > principal.max_priority:
            raise AppError(
                "PRIORITY_FORBIDDEN",
                f"当前账号最高可提交优先级 P{principal.max_priority}",
                status=403,
                detail={"requested": payload.priority, "max_priority": principal.max_priority},
            )
        set_row = await self.db.fetch_one(
            "SELECT * FROM scenario_set WHERE id=:id AND project=:project",
            {"id": payload.set_id, "project": project},
        )
        if set_row is None:
            raise not_found("场景集", payload.set_id)
        set_version = payload.set_version or int(set_row["current_version"])
        snapshot = await self.sets.load_snapshot(payload.set_id, set_version, principal, require_frozen=True)
        members = snapshot["members"]
        expected = len(members)
        if payload.batch.max_cases:
            expected = min(expected, payload.batch.max_cases)
        if expected <= 0:
            raise AppError("EMPTY_SET", "空场景集不能提交仿真任务", status=422)
        if principal.max_daily_cases is not None:
            used_row = await self.db.fetch_one(
                "SELECT COALESCE(SUM(total_cases),0) AS used FROM sim_task "
                "WHERE owner=:owner AND created_at >= date_trunc('day', now())",
                {"owner": principal.user},
            )
            used = int(used_row["used"]) if used_row else 0
            if used + expected > principal.max_daily_cases:
                raise AppError(
                    "DAILY_CASE_LIMIT",
                    f"今日 case 额度不足：已提交 {used}，本次 {expected}，上限 {principal.max_daily_cases}",
                    status=403,
                    detail={"used": used, "requested": expected, "limit": principal.max_daily_cases},
                )
        async with self.db.session() as session:
            fingerprint = await compute_fingerprint(
                session,
                payload=payload,
                project=project,
                set_id=payload.set_id,
                set_version=set_version,
                snapshot_sha=snapshot["snapshot_sha"],
            )
        if payload.dedup:
            duplicate = await self._find_duplicate(fingerprint, project, principal)
            if duplicate is not None:
                return duplicate
        task_id = payload.task_id or "tsk_" + utcnow().strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
        if await self.db.fetch_one("SELECT 1 FROM sim_task WHERE id=:id", {"id": task_id}):
            raise conflict("TASK_EXISTS", f"任务 {task_id} 已存在")
        try:
            if expected <= self.sync_limit:
                await self._submit_sync(
                    task_id, payload, principal, project, set_version, snapshot, fingerprint, expected
                )
            else:
                await self._submit_async(
                    task_id, payload, principal, project, set_version, snapshot, fingerprint, expected
                )
        except IntegrityError:
            if payload.dedup:
                duplicate = await self._find_duplicate(fingerprint, project, principal)
                if duplicate is not None:
                    return duplicate
            raise conflict("TASK_CONFLICT", "任务提交冲突，请重试") from None
        result = await self.get(task_id, principal)
        result["deduplicated"] = False
        return result

    @staticmethod
    def _scope_project(project: str, principal: Principal) -> str:
        if project != principal.project and not principal.admin:
            raise AppError("FORBIDDEN", "无权在该项目提交任务", status=403)
        return project

    async def _find_duplicate(
        self, fingerprint: str, project: str, principal: Principal
    ) -> dict[str, Any] | None:
        row = await self.db.fetch_one(
            "SELECT id FROM sim_task WHERE request_fingerprint=:fp AND dedup_enabled=true "
            "AND project=:project LIMIT 1",
            {"fp": fingerprint, "project": project},
        )
        if row is None:
            return None
        return {**await self.get(row["id"], principal), "deduplicated": True}

    async def _submit_sync(
        self,
        task_id: str,
        payload: SimTaskCreate,
        principal: Principal,
        project: str,
        set_version: int,
        snapshot: dict[str, Any],
        fingerprint: str,
        expected: int,
    ) -> None:
        created_at = utcnow()
        members = snapshot["members"][:expected]
        async with self.db.session() as session:
            await self._insert_task(
                session, task_id, payload, principal, project, set_version, snapshot, fingerprint,
                expected, "queued", expected, created_at,
            )
            await session.execute(
                text("INSERT INTO task_summary(task_id,total,queued) VALUES (:id,:total,:queued)"),
                {"id": task_id, "total": expected, "queued": expected},
            )
            for member in members:
                await self._insert_case(
                    session, task_id, member, payload, created_at, worker_id=None, status="queued"
                )
            await session.execute(
                text(
                    "INSERT INTO outbox(case_run_id,payload) "
                    "SELECT id, CAST(:payload AS JSONB) FROM case_run WHERE task_id=:tid AND created_at=:ct"
                ),
                {
                    "tid": task_id,
                    "ct": created_at,
                    "payload": dumps({"task_id": task_id, "event": "expand"}),
                },
            )
            await audit(session, principal, "task.submit", "sim_task", task_id, {"mode": "sync", "cases": expected})
            await session.commit()

    async def _submit_async(
        self,
        task_id: str,
        payload: SimTaskCreate,
        principal: Principal,
        project: str,
        set_version: int,
        snapshot: dict[str, Any],
        fingerprint: str,
        expected: int,
    ) -> None:
        created_at = utcnow()
        async with self.db.session() as session:
            await self._insert_task(
                session, task_id, payload, principal, project, set_version, snapshot, fingerprint,
                expected, "expanding", expected, created_at,
            )
            await session.execute(
                text("INSERT INTO task_summary(task_id,total) VALUES (:id,:total)"),
                {"id": task_id, "total": expected},
            )
            await session.execute(
                text(
                    "INSERT INTO task_expand_cursor(task_id,set_id,set_version,shard_index,last_offset,"
                    "case_run_created_at) VALUES (:id,:sid,:ver,0,0,:ct)"
                ),
                {"id": task_id, "sid": payload.set_id, "ver": set_version, "ct": created_at},
            )
            await audit(session, principal, "task.submit", "sim_task", task_id, {"mode": "async", "expected": expected})
            await session.commit()

    async def _insert_task(
        self,
        session: AsyncSession,
        task_id: str,
        payload: SimTaskCreate,
        principal: Principal,
        project: str,
        set_version: int,
        snapshot: dict[str, Any],
        fingerprint: str,
        expected: int,
        status: str,
        total: int,
        created_at: datetime,
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO sim_task(id,name,set_id,set_version,priority,runtime_config,metrics,project,owner,
                  total_cases,status,runtime_hash,request_fingerprint,dedup_enabled,snapshot_sha,engine_digest,
                  batch,seed,created_at)
                VALUES (:id,:name,:set_id,:set_ver,:priority,CAST(:runtime AS JSONB),CAST(:metrics AS TEXT[]),
                  :project,:owner,:total,:status,:runtime_hash,:fp,:dedup,:snapshot,:engine,
                  CAST(:batch AS JSONB),:seed,:created_at)
                """
            ),
            {
                "id": task_id,
                "name": payload.name or task_id,
                "set_id": payload.set_id,
                "set_ver": set_version,
                "priority": payload.priority,
                "runtime": dumps(payload.runtime.model_dump(mode="json")),
                "metrics": self.db.text_array(payload.metrics),
                "project": project,
                "owner": principal.user,
                "total": total,
                "status": status,
                "runtime_hash": sha256_text(dumps(payload.runtime.model_dump(mode="json"))),
                "fp": fingerprint,
                "dedup": payload.dedup,
                "snapshot": snapshot["snapshot_sha"],
                "engine": engine_digest(payload.runtime),
                "batch": dumps(payload.batch.model_dump()),
                "seed": payload.seed,
                "created_at": created_at,
            },
        )

    async def _insert_case(
        self,
        session: AsyncSession,
        task_id: str,
        member: dict[str, Any],
        payload: SimTaskCreate,
        created_at: datetime,
        *,
        worker_id: str | None,
        status: str,
    ) -> None:
        case_id = "run_" + sha256_text(f"{task_id}:{member['scenario_id']}")[7:31]
        await session.execute(
            text(
                """
                INSERT INTO case_run(id,task_id,scenario_id,scenario_version,priority,effective_priority,status,
                  attempt,worker_id,resource_req,waiting_since,created_at)
                VALUES (:id,:task_id,:scn,:sver,:priority,:priority,:status,0,:worker,
                  CAST(:resource AS JSONB),:created_at,:created_at)
                ON CONFLICT (task_id,scenario_id,created_at) DO NOTHING
                """
            ),
            {
                "id": case_id,
                "task_id": task_id,
                "scn": member["scenario_id"],
                "sver": member["scenario_version"],
                "priority": payload.priority,
                "status": status,
                "worker": worker_id,
                "resource": dumps(payload.runtime.resource.model_dump()),
                "created_at": created_at,
            },
        )

    # --------------------------------------------------------------- reads
    async def control(
        self, task_id: str, command: str, request_id: str, principal: Principal, reason: str = ""
    ) -> dict[str, Any]:
        task = await self.get(task_id, principal)
        existing = await self._existing_control(request_id, task_id, command)
        if existing is not None:
            return existing
        inflight = await self.db.fetch_one(
            "SELECT request_id FROM task_control_request WHERE task_id=:tid "
            "AND status IN ('pending','processing') LIMIT 1",
            {"tid": task_id},
        )
        if inflight:
            raise conflict("CONTROL_INFLIGHT", "该任务已有未完成控制请求", request_id=inflight["request_id"])
        rejection = _rejection(task["status"], command)
        try:
            await self._insert_control(request_id, task_id, command, principal, rejection, reason)
        except IntegrityError:
            existing = await self.db.fetch_one(
                "SELECT * FROM task_control_request WHERE request_id=:rid", {"rid": request_id}
            )
            if existing and existing["task_id"] == task_id and existing["command"] == command:
                return self._control_view(existing)
            raise conflict("REQUEST_ID_CONFLICT", "request_id 已被其他控制请求使用") from None
        row = await self.db.fetch_one(
            "SELECT * FROM task_control_request WHERE request_id=:rid", {"rid": request_id}
        )
        if row is None:
            raise conflict("CONTROL_CONFLICT", "控制请求写入冲突，请重试")
        return self._control_view(row)

    async def _insert_control(
        self,
        request_id: str,
        task_id: str,
        command: str,
        principal: Principal,
        rejection: str | None,
        reason: str,
    ) -> None:
        async with self.db.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO task_control_request(request_id,task_id,command,requested_by,status,result_code,
                      result_detail,completed_at)
                    VALUES (:rid,:tid,:cmd,:by,:status,:code,CAST(:detail AS JSONB),
                      CASE WHEN :status='rejected' THEN now() ELSE NULL END)
                    """
                ),
                {
                    "rid": request_id,
                    "tid": task_id,
                    "cmd": command,
                    "by": principal.user,
                    "status": "rejected" if rejection else "pending",
                    "code": rejection or "ACCEPTED",
                    "detail": dumps({"reason": reason}),
                },
            )
            await audit(
                session, principal, f"task.{command}", "sim_task", task_id, {"request_id": request_id}
            )
            await session.commit()

    async def _existing_control(
        self, request_id: str, task_id: str, command: str
    ) -> dict[str, Any] | None:
        row = await self.db.fetch_one(
            "SELECT * FROM task_control_request WHERE request_id=:rid", {"rid": request_id}
        )
        if row is None:
            return None
        if row["task_id"] != task_id or row["command"] != command:
            raise conflict("REQUEST_ID_CONFLICT", "request_id 已被其他控制请求使用")
        return self._control_view(row)

    # ------------------------------------------------------------ internals
def _rejection(task_status: str, command: str) -> str | None:
    terminal = {"succeeded", "failed", "canceled"}
    if command in {"pause", "resume"} and task_status == "expanding":
        return "EXPANDING"
    if command in {"pause", "resume"} and task_status in terminal:
        return "TERMINAL"
    if command == "resume" and task_status != "paused":
        return "NOT_PAUSED"
    if command == "pause" and task_status == "paused":
        return "ALREADY_PAUSED"
    if command == "cancel" and task_status in terminal:
        return "TERMINAL"
    return None
