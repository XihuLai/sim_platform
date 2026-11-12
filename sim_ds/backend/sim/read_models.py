"""Task read models: cursor pagination, summary charts and archive drilldown."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.scenario.common import loads, row_time
from backend.shared.auth import Principal
from backend.shared.canonical import encode_cursor, iso, utcnow
from backend.shared.db import Database
from backend.shared.errors import AppError, not_found
from backend.sim.status import counts_from_row


class TaskReadMixin:
    """Read-only TaskService surface, kept separate to respect file-size limits."""

    db: Database
    store: Any

    async def list_items(
        self,
        principal: Principal,
        *,
        status: str = "",
        priority: int | None = None,
        search: str = "",
        cursor: str | None = None,
        page_size: int = 50,
    ) -> dict[str, Any]:
        size = max(1, min(page_size, 200))
        clauses = ["t.project=:project"]
        params: dict[str, Any] = {"project": principal.project, "limit": size + 1}
        if status:
            clauses.append("t.status=:status")
            params["status"] = status
        if priority is not None:
            clauses.append("t.priority=:priority")
            params["priority"] = priority
        if search:
            clauses.append("(t.name ILIKE :search OR t.id ILIKE :search)")
            params["search"] = f"%{search}%"
        if cursor:
            from backend.shared.canonical import decode_cursor

            parts = decode_cursor(cursor, 2)
            clauses.append("(t.created_at, t.id) < (to_timestamp(:ct), :cid)")
            params["ct"] = float(parts[0])
            params["cid"] = parts[1]
        rows = await self.db.fetch_all(
            f"""
            SELECT t.*, s.total, s.queued, s.scheduled, s.running, s.paused, s.succeeded, s.failed,
                   s.canceled, s.timeout, s.worker_lost, s.pass_count, s.fail_count
            FROM sim_task t LEFT JOIN task_summary s ON s.task_id=t.id
            WHERE {' AND '.join(clauses)}
            ORDER BY t.created_at DESC, t.id DESC LIMIT :limit
            """,
            params,
        )
        has_more = len(rows) > size
        rows = rows[:size]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = encode_cursor(f"{last['created_at'].timestamp():.6f}", last["id"])
        return {"items": [self._task_view(row) for row in rows], "next_cursor": next_cursor}

    async def get(self, task_id: str, principal: Principal) -> dict[str, Any]:
        row = await self.db.fetch_one(
            """
            SELECT t.*, s.total, s.queued, s.scheduled, s.running, s.paused, s.succeeded, s.failed,
                   s.canceled, s.timeout, s.worker_lost, s.pass_count, s.fail_count
            FROM sim_task t LEFT JOIN task_summary s ON s.task_id=t.id
            WHERE t.id=:id AND t.project=:project
            """,
            {"id": task_id, "project": principal.project},
        )
        if row is None:
            raise not_found("任务", task_id)
        view = self._task_view(row)
        set_row = await self.db.fetch_one(
            "SELECT name, frozen FROM scenario_set WHERE id=:id", {"id": row["set_id"]}
        )
        view["set_name"] = set_row["name"] if set_row else None
        return view

    async def cases(
        self,
        task_id: str,
        principal: Principal,
        *,
        status: str = "",
        cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        task = await self.get(task_id, principal)
        size = max(1, min(page_size, 500))
        clauses = ["task_id=:tid"]
        params: dict[str, Any] = {"tid": task_id, "limit": size + 1}
        if status:
            clauses.append("status=:status")
            params["status"] = status
        if cursor:
            from backend.shared.canonical import decode_cursor

            parts = decode_cursor(cursor, 2)
            clauses.append("(created_at, id) > (to_timestamp(:ct), :cid)")
            params["ct"] = float(parts[0])
            params["cid"] = parts[1]
        rows = await self.db.fetch_all(
            f"SELECT * FROM case_run WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at, id LIMIT :limit",
            params,
        )
        has_more = len(rows) > size
        rows = rows[:size]
        metrics = await self._metrics_for([row["id"] for row in rows])
        items = [self._case_view(row, metrics.get(row["id"], {})) for row in rows]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = encode_cursor(f"{last['created_at'].timestamp():.6f}", last["id"])
        return {"items": items, "next_cursor": next_cursor, "task": {"id": task_id, "total_cases": task["total_cases"]}}

    async def case_detail(self, task_id: str, case_run_id: str, principal: Principal) -> dict[str, Any]:
        await self.get(task_id, principal)
        row = await self.db.fetch_one(
            "SELECT * FROM case_run WHERE task_id=:tid AND id=:cid ORDER BY created_at DESC LIMIT 1",
            {"tid": task_id, "cid": case_run_id},
        )
        if row is None:
            archived = await self._archived_case(task_id, case_run_id)
            if archived is not None:
                return archived
            raise not_found("CaseRun", case_run_id)
        metrics = await self._metrics_for([case_run_id])
        return self._case_view(row, metrics.get(case_run_id, {}))

    async def summary(self, task_id: str, principal: Principal) -> dict[str, Any]:
        task = await self.get(task_id, principal)
        rows = await self.db.fetch_all(
            "SELECT * FROM task_metric_agg WHERE task_id=:tid ORDER BY metric_key", {"tid": task_id}
        )
        failures = await self.db.fetch_all(
            """
            SELECT id, scenario_id, status, reason, attempt, worker_id, exit_code, finished_at
            FROM case_run WHERE task_id=:tid
              AND status IN ('failed','timeout','worker_lost','canceled')
            ORDER BY finished_at DESC NULLS LAST, id LIMIT 20
            """,
            {"tid": task_id},
        )
        total = task["total_cases"]
        succeeded = task["counts"]["succeeded"]
        pass_rate = round(task["pass_count"] * 100.0 / total, 2) if total else 0.0
        text_summary = (
            f"任务「{task['name']}」共 {total} 个用例，执行成功 {succeeded} 个，"
            f"指标通过 {task['pass_count']} 个，通过率 {pass_rate}%。"
        )
        if task["status"] in {"expanding", "queued", "scheduled", "running", "paused"}:
            text_summary = f"任务仍在{task['status']}阶段，当前完成 {succeeded}/{total}。"
        return {
            "task": task,
            "text": text_summary,
            "pass_rate": pass_rate,
            "metrics": rows,
            "charts": {
                "status": [{"key": key, "value": value} for key, value in task["counts"].items()],
                "metrics": [{"key": row["metric_key"], "cnt": row["cnt"], "pass_cnt": row["pass_cnt"],
                             "p95": row["p95_value"]} for row in rows],
            },
            "failures": [{**row, "finished_at": row_time(row, "finished_at")} for row in failures],
        }

    async def queue_stats(self, principal: Principal) -> dict[str, Any]:
        rows = await self.db.fetch_all(
            """
            SELECT t.status, COUNT(*) AS tasks, COALESCE(SUM(s.total),0) AS total_cases,
                   COALESCE(SUM(s.queued+s.scheduled),0) AS waiting_cases,
                   COALESCE(SUM(s.running),0) AS running_cases,
                   MIN(t.created_at) AS oldest_created
            FROM sim_task t LEFT JOIN task_summary s ON s.task_id=t.id
            WHERE t.project=:project
            GROUP BY t.status ORDER BY t.status
            """,
            {"project": principal.project},
        )
        priorities = await self.db.fetch_all(
            """
            SELECT t.priority, COUNT(*) AS tasks, COALESCE(SUM(s.queued),0) AS waiting
            FROM sim_task t LEFT JOIN task_summary s ON s.task_id=t.id
            WHERE t.project=:project AND t.status IN ('queued','scheduled','running','paused')
            GROUP BY t.priority ORDER BY t.priority
            """,
            {"project": principal.project},
        )
        return {
            "by_status": [{**row, "oldest_created": row_time(row, "oldest_created")} for row in rows],
            "by_priority": priorities,
            "generated_at": iso(utcnow()),
        }

    # ------------------------------------------------------------ controls

    async def cases_archive(
        self,
        task_id: str,
        principal: Principal,
        *,
        status: str = "",
        cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        await self.get(task_id, principal)
        size = max(1, min(page_size, 500))
        manifests = await self.db.fetch_all(
            "SELECT * FROM archive_export WHERE task_id=:tid AND status='completed' ORDER BY month",
            {"tid": task_id},
        )
        if not manifests:
            return {"items": [], "next_cursor": None, "archived": False, "message": "该任务尚无归档数据"}
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise AppError("ARCHIVE_UNAVAILABLE", "归档查询需要 pyarrow", status=503) from exc
        rows: list[dict[str, Any]] = []
        for manifest in manifests:
            path = Path(manifest["parquet_uri"])
            if not path.is_absolute() and self.store is not None:
                path = self.store.resolve(manifest["parquet_uri"])
            if not path.exists():
                continue
            table = pq.read_table(path)
            for item in table.to_pylist():
                if status and item.get("status") != status:
                    continue
                rows.append(item)
        rows.sort(key=lambda item: (str(item.get("created_at")), str(item.get("id"))))
        if cursor:
            from backend.shared.canonical import decode_cursor

            parts = decode_cursor(cursor, 2)
            rows = [item for item in rows if (str(item.get("created_at")), str(item.get("id"))) > (parts[0], parts[1])]
        page = rows[:size]
        next_cursor = None
        if len(rows) > size and page:
            last = page[-1]
            next_cursor = encode_cursor(str(last.get("created_at")), str(last.get("id")))
        return {"items": page, "next_cursor": next_cursor, "archived": True}

    async def _metrics_for(self, case_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not case_ids:
            return {}
        rows = await self.db.fetch_all(
            "SELECT case_run_id, metric_key, value, pass FROM case_result "
            "WHERE case_run_id = ANY(CAST(:ids AS TEXT[]))",
            {"ids": self.db.text_array(case_ids)},
        )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            result.setdefault(row["case_run_id"], {})[row["metric_key"]] = {
                "value": row["value"],
                "pass": row["pass"],
            }
        return result

    async def _archived_case(self, task_id: str, case_run_id: str) -> dict[str, Any] | None:
        manifest = await self.db.fetch_one(
            "SELECT * FROM archive_export WHERE task_id=:tid AND status='completed' LIMIT 1", {"tid": task_id}
        )
        if manifest is None:
            return None
        return {
            "case_run_id": case_run_id,
            "task_id": task_id,
            "archived": True,
            "archive_uri": manifest["parquet_uri"],
            "status": "archived",
        }

    def _task_view(self, row: dict[str, Any]) -> dict[str, Any]:
        counts = counts_from_row(row)
        total = int(row.get("total") or row.get("total_cases") or 0)
        view = {
            "task_id": row["id"],
            "name": row["name"],
            "project": row["project"],
            "owner": row["owner"],
            "set_id": row["set_id"],
            "set_version": row["set_version"],
            "priority": row["priority"],
            "runtime": loads(row["runtime_config"]),
            "metrics": row["metrics"],
            "batch": loads(row.get("batch") or {}),
            "seed": row.get("seed"),
            "status": row["status"],
            "total_cases": total,
            "snapshot_sha": row["snapshot_sha"],
            "request_fingerprint": row["request_fingerprint"],
            "created_at": row_time(row, "created_at"),
            "started_at": row_time(row, "started_at"),
            "finished_at": row_time(row, "finished_at"),
            "counts": counts,
            "pass_count": int(row.get("pass_count") or 0),
            "fail_count": int(row.get("fail_count") or 0),
            "progress": round((counts["succeeded"] + counts["failed"] + counts["canceled"] + counts["timeout"] + counts["worker_lost"]) * 100.0 / total, 2) if total else 0.0,
        }
        return view

    def _case_view(self, row: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
        return {
            "case_run_id": row["id"],
            "task_id": row["task_id"],
            "scenario_id": row["scenario_id"],
            "scenario_version": row["scenario_version"],
            "status": row["status"],
            "attempt": row["attempt"],
            "worker_id": row["worker_id"],
            "exit_code": row["exit_code"],
            "output_uri": row["output_uri"],
            "reason": row["reason"],
            "metrics": metrics,
            "created_at": row_time(row, "created_at"),
            "started_at": row_time(row, "started_at"),
            "finished_at": row_time(row, "finished_at"),
        }

    def _control_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "request_id": row["request_id"],
            "task_id": row["task_id"],
            "command": row["command"],
            "status": row["status"],
            "result_code": row["result_code"],
            "detail": loads(row["result_detail"]),
            "created_at": row_time(row, "created_at"),
            "completed_at": row_time(row, "completed_at"),
            "accepted": row["status"] != "rejected",
        }


