"""Scenario projection, lookup and publication recovery helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.models import MetricConfig, ScenarioMetricInstance
from backend.scenario.common import load_metric_def, loads, row_time, scenario_uri
from backend.scenario.metrics import validate_instance, validate_required_templates
from backend.shared.db import Database, dumps
from backend.shared.errors import AppError, not_found
from backend.shared.files import FileStore


class ScenarioSupport:
    """Mixin with projection and version lifecycle helpers."""

    db: Database
    store: FileStore

    async def _write_projection(
        self, session: AsyncSession, scenario_id: str, document: dict[str, Any]
    ) -> None:
        await session.execute(
            text(
                """
                UPDATE scenario SET name=:name, description=:desc, source_type=:stype, log_id=:log_id,
                  log_uri=:log_uri, log_checksum=:log_sha, start_ts=:start, end_ts=:end, trigger_ts=:trig,
                  extra=CAST(:extra AS JSONB), updated_at=now()
                WHERE id=:id
                """
            ),
            {
                "id": scenario_id,
                "name": document["name"],
                "desc": document["description"],
                "stype": document["source"]["type"],
                "log_id": document["source"].get("log_id", ""),
                "log_uri": document["source"].get("log_uri", ""),
                "log_sha": document["source"].get("log_checksum", ""),
                "start": document["time_window"]["start_ts"],
                "end": document["time_window"]["end_ts"],
                "trig": document["time_window"]["trigger_ts"],
                "extra": dumps(document["extra"]),
            },
        )
        await self._write_metrics(session, scenario_id, document["metrics"])
        await self._write_tags(session, scenario_id, document["tags"])

    async def _write_metrics(
        self, session: AsyncSession, scenario_id: str, metrics: list[dict[str, Any]]
    ) -> None:
        await session.execute(text("DELETE FROM scenario_metric WHERE scenario_id=:sid"), {"sid": scenario_id})
        for item in metrics:
            instance = await self._metric_instance(session, item)
            await session.execute(
                text(
                    """
                    INSERT INTO scenario_metric(scenario_id,metric_def_id,metric_def_ver,alias,config,enabled,extra)
                    VALUES (:sid,:did,:dver,:alias,CAST(:config AS JSONB),:enabled,CAST(:extra AS JSONB))
                    """
                ),
                {
                    "sid": scenario_id,
                    "did": instance.metric_def_id,
                    "dver": instance.metric_def_ver,
                    "alias": instance.alias,
                    "config": dumps(instance.config.model_dump(mode="json")),
                    "enabled": instance.enabled,
                    "extra": dumps(instance.extra),
                },
            )

    async def _write_tags(self, session: AsyncSession, scenario_id: str, tags: list[str]) -> None:
        await session.execute(text("DELETE FROM scenario_tag WHERE scenario_id=:sid"), {"sid": scenario_id})
        for name in tags:
            await session.execute(
                text(
                    "INSERT INTO tag(name,category) VALUES (:name,'scenario') "
                    "ON CONFLICT (name,category) DO NOTHING"
                ),
                {"name": name},
            )
            await session.execute(
                text(
                    "INSERT INTO scenario_tag(scenario_id,tag_id) "
                    "SELECT :sid, id FROM tag WHERE name=:name AND category='scenario' "
                    "ON CONFLICT DO NOTHING"
                ),
                {"sid": scenario_id, "name": name},
            )

    async def _metric_instance(
        self, session: AsyncSession, item: dict[str, Any]
    ) -> ScenarioMetricInstance:
        metric_id = str(item.get("id") or "")
        if not metric_id:
            raise AppError("METRIC_ID_REQUIRED", "Scenario metric 缺少 id", status=422)
        row = await session.execute(
            text(
                "SELECT version FROM metric_def WHERE id=:id AND status='active' "
                "ORDER BY version DESC LIMIT 1"
            ),
            {"id": metric_id},
        )
        found = row.first()
        if found is None:
            raise AppError("METRIC_DEF_NOT_FOUND", f"Metric 定义 {metric_id} 不存在", status=422)
        version = int(found[0])
        config = MetricConfig(
            trigger_functions=item.get("trigger_functions", []),
            trigger_ops=item.get("trigger_ops", []),
            functions=item.get("functions", []),
            ops=item.get("ops", []),
            ret=item.get("ret", "pass"),
            action=item.get("action", "not_stop_sim"),
            level=item.get("level", "S0"),
            is_global=item.get("is_global", False),
        )
        instance = ScenarioMetricInstance(
            metric_def_id=metric_id,
            metric_def_ver=version,
            alias=None,
            config=config,
            enabled=True,
            extra={},
        )
        definition = await _definition(session, metric_id, version)
        await validate_instance(session, instance)
        validate_required_templates(definition, instance.config)
        return instance

    async def _normalize_metrics(self, payload: dict[str, Any]) -> None:
        normalized: list[dict[str, Any]] = []
        for item in payload.get("metrics", []):
            if "metric_def_id" not in item:
                normalized.append(item)
                continue
            legacy_id = str(item.get("metric_def_id"))
            metric_id = LEGACY_METRIC_IDS.get(legacy_id, legacy_id)
            try:
                async with self.db.session() as lookup:
                    definition = await _definition(
                        lookup, metric_id, int(item.get("metric_def_ver", 1))
                    )
            except Exception:
                normalized.append(
                    {
                        "id": metric_id,
                        "name": metric_id,
                        "desc": "",
                        "business_type": "dpc",
                        "run_mode": "async",
                        "level": "S0",
                        "is_global": False,
                        **item.get("config", {}),
                    }
                )
                continue
            config = item.get("config", {})
            normalized.append(
                {
                    "id": metric_id,
                    "name": definition.name,
                    "desc": definition.description,
                    "business_type": definition.business_type,
                    "run_mode": definition.run_mode,
                    "level": config.get("level", definition.level),
                    "is_global": config.get("is_global", definition.is_global),
                    "trigger_functions": config.get("trigger_functions", []),
                    "trigger_ops": config.get("trigger_ops", []),
                    "functions": config.get("functions", []),
                    "ops": config.get("ops", []),
                    "ret": config.get("ret", definition.ret),
                    "action": config.get("action", definition.action),
                }
            )
        payload["metrics"] = normalized

    def _list_item(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row.get("description"),
            "version": row["current_version"],
            "status": row["status"],
            "source_type": row["source_type"],
            "duration_ms": row.get("duration_ms"),
            "tags": list(row.get("tags") or []),
            "owner": row.get("owner"),
            "project": row.get("project"),
            "created_at": row_time(row, "created_at"),
            "updated_at": row_time(row, "updated_at"),
        }

    async def _scenario_row(self, scenario_id: str, project: str) -> dict[str, Any]:
        row = await self.db.fetch_one(
            "SELECT * FROM scenario WHERE id=:id AND project=:project",
            {"id": scenario_id, "project": project},
        )
        if row is None:
            raise not_found("场景", scenario_id)
        return row

    async def _version_row(self, scenario_id: str, version: int) -> dict[str, Any] | None:
        return await self.db.fetch_one(
            "SELECT * FROM scenario_version WHERE scenario_id=:sid AND version=:ver",
            {"sid": scenario_id, "ver": version},
        )

    def _read_verified(self, version_row: dict[str, Any]) -> dict[str, Any]:
        uri = version_row["file_uri"]
        expected = version_row["file_checksum"]
        if not self.store.verify(uri, expected):
            raise AppError(
                "VERSION_UNAVAILABLE",
                "场景版本文件缺失或校验失败，已标记不可用",
                status=409,
                detail={"scenario_id": version_row["scenario_id"], "version": version_row["version"]},
            )
        import json

        payload: dict[str, Any] = loads(json.loads(self.store.read_bytes(self.store.resolve(uri))))
        return payload

    async def _scenario_tags(self, scenario_id: str) -> list[str]:
        rows = await self.db.fetch_all(
            "SELECT t.name FROM scenario_tag st JOIN tag t ON t.id=st.tag_id "
            "WHERE st.scenario_id=:sid ORDER BY t.name",
            {"sid": scenario_id},
        )
        return [row["name"] for row in rows]

    async def recover_pending(self) -> dict[str, int]:
        rows = await self.db.fetch_all(
            "SELECT * FROM scenario_version WHERE publish_state='pending' ORDER BY created_at"
        )
        completed = failed = 0
        for row in rows:
            uri = row["file_uri"]
            expected = row["file_checksum"]
            if self.store.verify(uri, expected):
                await self._mark_published(row["scenario_id"], row["version"], expected)
                completed += 1
                continue
            promoted = self.store.recover_temp(uri)
            if promoted and promoted.checksum == expected:
                await self._mark_published(row["scenario_id"], row["version"], expected)
                completed += 1
            else:
                await self.db.execute(
                    "UPDATE scenario_version SET publish_state='failed' WHERE scenario_id=:sid AND version=:ver",
                    {"sid": row["scenario_id"], "ver": row["version"]},
                )
                failed += 1
        return {"completed": completed, "failed": failed}

    async def _mark_published(self, scenario_id: str, version: int, checksum: str) -> None:
        async with self.db.session() as session:
            await session.execute(
                text(
                    "UPDATE scenario_version SET publish_state='published', file_checksum=:sha "
                    "WHERE scenario_id=:sid AND version=:ver"
                ),
                {"sid": scenario_id, "ver": version, "sha": checksum},
            )
            await session.execute(
                text(
                    "UPDATE scenario SET current_version=GREATEST(current_version,:ver), file_uri=:uri, "
                    "file_checksum=:sha WHERE id=:sid"
                ),
                {"sid": scenario_id, "ver": version, "uri": scenario_uri(scenario_id, version), "sha": checksum},
            )
            await session.commit()

    async def mark_unavailable(self, scenario_id: str, version: int) -> None:
        await self.db.execute(
            "UPDATE scenario_version SET publish_state='unavailable' WHERE scenario_id=:sid AND version=:ver",
            {"sid": scenario_id, "ver": version},
        )


async def _definition(session: AsyncSession, metric_def_id: str, version: int) -> Any:

    definition = await load_metric_def(session, metric_def_id, version)
    if definition is None:
        raise AppError(
            "METRIC_DEF_NOT_FOUND",
            f"Metric 定义 {metric_def_id}@{version} 不存在",
            status=422,
        )
    return definition


LEGACY_METRIC_IDS = {
    "safety.brake.hard": "3001",
    "safety.collision.rate": "3002",
    "comfort.jerk": "1002",
    "efficiency.speed": "4001",
    "38": "1001",
    "39": "2001",
    "37139": "2002",
    "18": "3001",
    "33": "5001",
    "920": "5002",
}
