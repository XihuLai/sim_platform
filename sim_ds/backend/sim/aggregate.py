"""Incremental aggregation, reconciliation and state-transition helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.shared.db import Database, dumps
from backend.sim.status import counts_from_row, derive_task_status

COUNT_KEYS = {
    "queued", "scheduled", "running", "paused", "succeeded",
    "failed", "canceled", "timeout", "worker_lost",
}


_PASS_TOTALS_SQL = """
UPDATE task_summary ts SET
  pass_count = agg.pass_count,
  fail_count = agg.fail_count,
  updated_at = now()
FROM (
  SELECT c.task_id,
         COUNT(*) FILTER (
           WHERE c.status='succeeded' AND NOT EXISTS (
             SELECT 1 FROM case_result r WHERE r.case_run_id=c.id AND r.pass IS FALSE
           )
         ) AS pass_count,
         COUNT(*) FILTER (
           WHERE c.status <> 'canceled' AND (
             c.status <> 'succeeded' OR EXISTS (
               SELECT 1 FROM case_result r WHERE r.case_run_id=c.id AND r.pass IS FALSE
             )
           )
         ) AS fail_count
  FROM case_run c
  WHERE c.task_id=:tid
  GROUP BY c.task_id
) agg
WHERE ts.task_id=agg.task_id
"""



class ResultAggregateMixin:
    db: Database

    async def refresh_task_status(self, session: AsyncSession, task_id: str) -> str:
        task = (
            await session.execute(
                text("SELECT status FROM sim_task WHERE id=:id"), {"id": task_id}
            )
        ).first()
        if task is None:
            return "failed"
        summary = (
            await session.execute(
                text("SELECT * FROM task_summary WHERE task_id=:id"), {"id": task_id}
            )
        ).mappings().first()
        counts = counts_from_row(dict(summary) if summary else None)
        total = int(summary["total"]) if summary else 0
        expanding = task[0] == "expanding"
        latest = (
            await session.execute(
                text(
                    "SELECT command, status FROM task_control_request WHERE task_id=:id "
                    "ORDER BY created_at DESC, request_id DESC LIMIT 1"
                ),
                {"id": task_id},
            )
        ).mappings().first()
        cancel = await self._has_control(session, task_id, "cancel")
        pause = bool(latest and latest["command"] == "pause" and latest["status"] in {"pending", "processing", "completed"})
        status = derive_task_status(counts, total=total, expanding=expanding, cancel_accepted=cancel, pause_accepted=pause)
        finished = status in {"succeeded", "failed", "canceled"}
        await session.execute(
            text(
                "UPDATE sim_task SET status=:status, total_cases=:total, "
                "started_at=CASE WHEN :started AND started_at IS NULL THEN now() ELSE started_at END, "
                "finished_at=CASE WHEN :finished THEN COALESCE(finished_at, now()) ELSE NULL END WHERE id=:id"
            ),
            {
                "id": task_id,
                "status": status,
                "total": total,
                "started": counts["running"] + counts["scheduled"] + counts["paused"] > 0,
                "finished": finished,
            },
        )
        return str(status)

    async def reconcile(self) -> int:
        rows = await self.db.fetch_all(
            "SELECT task_id FROM task_summary WHERE updated_at > now() - interval '1 day'"
        )
        fixed = 0
        for row in rows:
            async with self.db.session() as session:
                counts = (
                    await session.execute(
                        text(
                            "SELECT status, COUNT(*) AS n FROM case_run WHERE task_id=:tid GROUP BY status"
                        ),
                        {"tid": row["task_id"]},
                    )
                ).mappings().all()
                values = {item["status"]: int(item["n"]) for item in counts}
                total = sum(values.values())
                assignments = ", ".join(
                    f"{key}=:v_{key}" for key in COUNT_KEYS
                )
                params: dict[str, Any] = {f"v_{key}": values.get(key, 0) for key in COUNT_KEYS}
                params.update({"tid": row["task_id"], "total": total})
                await session.execute(
                    text(
                        f"UPDATE task_summary SET {assignments}, total=:total, updated_at=now() "
                        "WHERE task_id=:tid"
                    ),
                    params,
                )
                await session.execute(text(_PASS_TOTALS_SQL), {"tid": row["task_id"]})
                await self.refresh_task_status(session, row["task_id"])
                await session.commit()
                fixed += 1
        return fixed

    async def recompute_p95(self) -> int:
        rows = await self.db.fetch_all(
            "SELECT DISTINCT task_id FROM task_metric_agg WHERE updated_at > now() - interval '1 day'"
        )
        for row in rows:
            await self.db.execute(
                """
                UPDATE task_metric_agg a SET p95_value=(
                  SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY r.value)
                  FROM case_result r WHERE r.task_id=a.task_id AND r.metric_key=a.metric_key
                    AND r.value IS NOT NULL
                ), updated_at=now()
                WHERE a.task_id=:tid
                """,
                {"tid": row["task_id"]},
            )
        return len(rows)

    # ------------------------------------------------------------ internals
    async def _bump_passed(
        self, session: AsyncSession, task_id: str, status: str, metrics: dict[str, Any]
    ) -> None:
        passed = status == "succeeded" and all(
            not (isinstance(value, dict) and value.get("pass") is False) for value in metrics.values()
        )
        if passed:
            await session.execute(
                text("UPDATE task_summary SET pass_count=pass_count+1, updated_at=now() WHERE task_id=:tid"),
                {"tid": task_id},
            )
        elif status != "canceled":
            await session.execute(
                text("UPDATE task_summary SET fail_count=fail_count+1, updated_at=now() WHERE task_id=:tid"),
                {"tid": task_id},
            )

    async def _write_results(
        self,
        session: AsyncSession,
        case: dict[str, Any],
        attempt: int,
        metrics: dict[str, Any],
        output_uri: str,
    ) -> None:
        for metric_key, value in metrics.items():
            if not isinstance(value, dict):
                value = {"value": value}
            await session.execute(
                text(
                    """
                    INSERT INTO case_result(case_run_id,task_id,scenario_id,metric_key,value,pass,extra,attempt,created_at)
                    VALUES (:cid,:tid,:sid,:key,:value,:pass,CAST(:extra AS JSONB),:attempt,now())
                    """
                ),
                {
                    "cid": case["id"],
                    "tid": case["task_id"],
                    "sid": case["scenario_id"],
                    "key": metric_key,
                    "value": value.get("value"),
                    "pass": value.get("pass"),
                    "extra": dumps({"output_uri": output_uri}),
                    "attempt": attempt,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO task_metric_agg(task_id,metric_key,cnt,pass_cnt,sum_value)
                    VALUES (:tid,:key,1,:pass,:value)
                    ON CONFLICT (task_id,metric_key) DO UPDATE SET
                      cnt=task_metric_agg.cnt+1,
                      pass_cnt=task_metric_agg.pass_cnt + EXCLUDED.pass_cnt,
                      sum_value=task_metric_agg.sum_value + EXCLUDED.sum_value,
                      updated_at=now()
                    """
                ),
                {
                    "tid": case["task_id"],
                    "key": metric_key,
                    "pass": 1 if value.get("pass") else 0,
                    "value": float(value.get("value") or 0),
                },
            )

    async def bump(self, session: AsyncSession, task_id: str, deltas: dict[str, int]) -> None:
        clean = {key: delta for key, delta in deltas.items() if key in COUNT_KEYS and delta}
        if not clean:
            return
        assignments = ", ".join(f"{key}=GREATEST(0,{key}+:d_{key})" for key in clean)
        params: dict[str, Any] = {f"d_{key}": delta for key, delta in clean.items()}
        params["tid"] = task_id
        await session.execute(
            text(f"UPDATE task_summary SET {assignments}, updated_at=now() WHERE task_id=:tid"), params
        )

    async def _release(self, session: AsyncSession, case_run_id: str, attempt: int) -> None:
        await session.execute(
            text(
                "UPDATE resource_reservation SET released_at=now() "
                "WHERE case_run_id=:cid AND attempt=:attempt AND released_at IS NULL"
            ),
            {"cid": case_run_id, "attempt": attempt},
        )

    async def _has_control(self, session: AsyncSession, task_id: str, command: str) -> bool:
        row = (
            await session.execute(
                text(
                    "SELECT 1 FROM task_control_request WHERE task_id=:tid AND command=:cmd "
                    "AND status IN ('pending','processing','completed') LIMIT 1"
                ),
                {"tid": task_id, "cmd": command},
            )
        ).first()
        return row is not None

    async def _case_for_update(self, session: AsyncSession, case_run_id: str) -> dict[str, Any] | None:
        row = (
            await session.execute(
                text("SELECT * FROM case_run WHERE id=:id ORDER BY created_at DESC LIMIT 1 FOR UPDATE"),
                {"id": case_run_id},
            )
        ).mappings().first()
        return dict(row) if row else None

    async def _task(self, session: AsyncSession, task_id: str) -> dict[str, Any]:
        row = (
            await session.execute(text("SELECT * FROM sim_task WHERE id=:id"), {"id": task_id})
        ).mappings().first()
        if row is None:
            raise LookupError(task_id)
        return dict(row)
