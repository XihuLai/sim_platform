#!/usr/bin/env python3
"""Import metric definitions from one or more metric JSON files.

The source format is the scenario-style ``{"metrics": [...]}`` document with
``trigger_functions`` / ``trigger_ops`` / ``functions``. Missing template rows
are created from the env sample; metric IDs are preserved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from backend.domain.models import MetricDef, MetricTemplate, MetricType
from backend.scenario.metrics_service import MetricService
from backend.shared.auth import Principal
from backend.shared.config import load_settings
from backend.shared.db import Database

METRIC_ID_MAP = {
    "18": "3001",
    "33": "5001",
    "38": "1001",
    "39": "2001",
    "920": "5002",
    "37139": "2002",
}

TYPE_BY_ID = {
    "18": "safety.brake",
    "33": "navigation.lane",
    "38": "comfort.ride",
    "39": "compliance.steering",
    "920": "navigation.lane",
    "37139": "compliance.dlp",
}

EXTRA_TYPES = [
    MetricType(id="compliance.steering", category_id="compliance", name="转向合规", sort_order=1),
    MetricType(id="compliance.dlp", category_id="compliance", name="DLP 合规", sort_order=2),
]


def env_schema(env: dict[str, Any]) -> dict[str, Any]:
    properties = {}
    for key in env:
        properties[key] = {
            "type": "object",
            "required": ["field_name", "value", "is_number", "unit"],
            "properties": {
                "field_name": {"type": "string"},
                "value": {"type": "string"},
                "is_number": {"type": "boolean"},
                "unit": {"type": "string"},
            },
        }
    return {"type": "object", "required": list(env.keys()), "properties": properties}


async def ensure_type(service: MetricService, type_id: str, principal: Principal) -> None:
    existing = {item["id"] for item in await service.types()}
    for item in EXTRA_TYPES:
        if item.id not in existing:
            try:
                await service.create_type(item, principal)
            except Exception:
                pass
    if type_id not in existing and not any(item.id == type_id for item in EXTRA_TYPES):
        raise SystemExit(f"metric type not found: {type_id}")


async def ensure_templates(
    service: MetricService,
    metrics: list[dict[str, Any]],
    principal: Principal,
) -> None:
    existing = {item["id"] for item in await service.templates()}
    for metric in metrics:
        groups = [
            ("trigger", metric.get("trigger_functions", [])),
            ("function", metric.get("functions", [])),
        ]
        for kind, items in groups:
            for item in items:
                template_id = str(item.get("template_id", ""))
                if not template_id or template_id in existing:
                    continue
                env = item.get("env") or {}
                name = str(item.get("function_field_name") or item.get("name") or template_id)
                template = MetricTemplate(
                    id=template_id,
                    name=name,
                    kind=kind,
                    env_schema=env_schema(env),
                    env_example=env,
                )
                await service.create_template(template, principal)
                existing.add(template_id)


async def import_file(
    service: MetricService,
    path: Path,
    principal: Principal,
) -> int:
    document = json.loads(path.read_text(encoding="utf-8"))
    metrics = document.get("metrics", [])
    await ensure_templates(service, metrics, principal)
    imported = 0
    for item in metrics:
        metric_id = METRIC_ID_MAP.get(str(item["id"]), str(item["id"]))
        type_id = TYPE_BY_ID.get(metric_id)
        if type_id is None:
            type_id = "safety.brake"
        await ensure_type(service, type_id, principal)
        exists = await service.db.fetch_one(
            "SELECT 1 FROM metric_def WHERE id=:id", {"id": metric_id}
        )
        if exists:
            continue
        definition = MetricDef(
            id=metric_id,
            version=1,
            type_id=type_id,
            name=str(item.get("name", metric_id)),
            level=str(item.get("level", "S0")),
            business_type=str(item.get("business_type", "dpc")),
            run_mode=str(item.get("run_mode", "async")),  # type: ignore[arg-type]
            is_global=bool(item.get("is_global", False)),
            trigger_functions=item.get("trigger_functions", []),
            trigger_ops=item.get("trigger_ops", []),
            functions=item.get("functions", []),
            ops=item.get("ops", []),
            ret=str(item.get("ret", "pass")),  # type: ignore[arg-type]
            action=str(item.get("action", "not_stop_sim")),
            description=str(item.get("desc", "")),
        )
        await service.create_def(definition, principal)
        imported += 1
    return imported


async def main(files: list[Path]) -> None:
    settings = load_settings()
    db = Database(settings.database_url)
    service = MetricService(db)
    principal = Principal(user="df_sim", project="default", projects=("default",), admin=True, role="super_admin")
    try:
        await db.execute("DELETE FROM metric_def WHERE id IN ('demo.ui_metric', 'safety.json.ui')")
        total = 0
        for path in files:
            count = await import_file(service, path, principal)
            print(f"{path}: imported {count} metric(s)")
            total += count
        print(f"done: {total} metric definition(s) imported")
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.files))
