"""Request fingerprint: all inputs that must reproduce a task exactly."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.models import RuntimeConfig, SimTaskCreate
from backend.scenario.common import loads
from backend.shared.canonical import sha256_json, sha256_text


async def compute_fingerprint(
    session: AsyncSession,
    *,
    payload: SimTaskCreate,
    project: str,
    set_id: str,
    set_version: int,
    snapshot_sha: str,
) -> str:
    seed = payload.seed if payload.seed is not None else int(payload.runtime.env.get("SIM_SEED", "0"))
    fingerprint_input = {
        "project": project,
        "snapshot": snapshot_sha,
        "set": {"id": set_id, "version": set_version},
        "scenarios": await _scenarios(session, set_id, set_version),
        "metric_configs": await _metric_configs(session, set_id, set_version),
        "metrics": sorted(payload.metrics),
        "engine_digest": engine_digest(payload.runtime),
        "runtime": _canonical_runtime(payload.runtime),
        "seed": seed,
    }
    return sha256_json(fingerprint_input)


async def _scenarios(session: AsyncSession, set_id: str, set_version: int) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT m.scenario_id, m.scenario_version, v.file_checksum
                FROM scenario_set_member m
                LEFT JOIN scenario_version v
                  ON v.scenario_id=m.scenario_id AND v.version=m.scenario_version
                WHERE m.set_id=:sid AND m.set_version=:ver
                ORDER BY m.scenario_id
                """
            ),
            {"sid": set_id, "ver": set_version},
        )
    ).mappings().all()
    return [
        {"scenario_id": row["scenario_id"], "version": row["scenario_version"], "checksum": row["file_checksum"]}
        for row in rows
    ]


async def _metric_configs(session: AsyncSession, set_id: str, set_version: int) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT m.scenario_id, sm.metric_def_id, sm.metric_def_ver, sm.alias, sm.config
                FROM scenario_set_member m
                JOIN scenario_metric sm ON sm.scenario_id=m.scenario_id
                WHERE m.set_id=:sid AND m.set_version=:ver
                ORDER BY m.scenario_id, sm.metric_def_id, sm.alias NULLS FIRST
                """
            ),
            {"sid": set_id, "ver": set_version},
        )
    ).mappings().all()
    return [
        {
            "scenario_id": row["scenario_id"],
            "metric_def_id": row["metric_def_id"],
            "version": row["metric_def_ver"],
            "alias": row["alias"],
            "config": loads(row["config"]),
        }
        for row in rows
    ]


def engine_digest(runtime: RuntimeConfig) -> str:
    if runtime.binary_uri:
        return sha256_text(
            "artifact:" + runtime.binary_uri + ":" + str(runtime.binary_checksum)
        )
    return sha256_text("artifact:" + runtime.binary_id)


def _canonical_runtime(runtime: RuntimeConfig) -> dict[str, Any]:
    result: dict[str, Any] = {
        "binary_id": runtime.binary_id,
        "args": runtime.args,
        "env": {key: runtime.env[key] for key in sorted(runtime.env)},
        "resource": runtime.resource.model_dump(),
        "timeout_sec": runtime.timeout_sec,
        "retry": runtime.retry.model_dump(),
    }
    if runtime.binary_uri:
        result["binary_uri"] = runtime.binary_uri
        result["binary_checksum"] = runtime.binary_checksum
    return result
