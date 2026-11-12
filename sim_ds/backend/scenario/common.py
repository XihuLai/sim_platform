"""Scenario domain shared helpers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.models import MetricDef, ScenarioMetricInstance
from backend.shared.errors import AppError


def loads(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


def scenario_uri(scenario_id: str, version: int) -> str:
    return f"scenarios/{scenario_id}/v{version}.json"


def set_uri(set_id: str, version: int) -> str:
    return f"sets/{set_id}/v{version}.json"


def set_meta_uri(set_id: str, version: int) -> str:
    return f"sets/{set_id}/v{version}.meta.json"


def set_shard_uri(set_id: str, version: int, shard: int) -> str:
    return f"sets/{set_id}/v{version}.members.{shard}.json"


def row_time(row: dict[str, Any], key: str) -> str | None:
    value = row.get(key)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


async def load_metric_def(
    session: AsyncSession, metric_def_id: str, version: int
) -> MetricDef | None:
    row = (
        await session.execute(
            text("SELECT * FROM metric_def WHERE id = :id AND version = :ver"),
            {"id": metric_def_id, "ver": version},
        )
    ).mappings().first()
    if row is None:
        return None
    data = dict(row)
    for key in (
        "trigger_templates",
        "trigger_ops",
        "function_templates",
        "ops",
    ):
        data[key] = loads(data.get(key) or [])
    return MetricDef.model_validate(data)


async def metric_instances(
    session: AsyncSession, scenario_id: str, version: int | None = None
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT metric_def_id, metric_def_ver, alias, config, enabled, extra
                FROM scenario_metric WHERE scenario_id = :sid
                ORDER BY metric_def_id, alias NULLS FIRST
                """
            ),
            {"sid": scenario_id},
        )
    ).mappings().all()
    return [
        {
            "metric_def_id": row["metric_def_id"],
            "metric_def_ver": row["metric_def_ver"],
            "alias": row["alias"],
            "config": loads(row["config"]),
            "enabled": row["enabled"],
            "extra": loads(row["extra"]),
        }
        for row in rows
    ]


def instance_dict(instance: ScenarioMetricInstance) -> dict[str, Any]:
    return instance.model_dump(mode="json")


def ensure_version_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("scenario_id") or not payload.get("name"):
        raise AppError("INVALID_SCENARIO", "场景文件缺少 scenario_id 或 name", status=422)
    return payload
