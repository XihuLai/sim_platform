"""Demo corpus builders used by scripts/seed.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.domain.models import (
    DataSourceCreate,
    MetricDef,
    MetricType,
    ScenarioCreate,
    SetCreate,
    SetMember,
)
from backend.playback.service import PlaybackService
from backend.scenario.metrics_service import MetricService
from backend.scenario.service import ScenarioService
from backend.scenario.sets import SetService
from backend.shared.auth import Principal
from backend.shared.db import Database

METRIC_TYPES = [
    MetricType(id="safety.brake", category_id="safety", name="制动类", sort_order=1),
    MetricType(id="safety.collision", category_id="safety", name="碰撞类", sort_order=2),
    MetricType(id="comfort.ride", category_id="comfort", name="乘坐舒适", sort_order=1),
    MetricType(id="4001", category_id="efficiency", name="通行效率", sort_order=1),
    MetricType(id="navigation.lane", category_id="navigation", name="车道保持", sort_order=1),
]

METRIC_DEFS = [
    MetricDef(
        id="3001",
        version=1,
        type_id="safety.brake",
        name="急刹",
        level="S0",
        trigger_templates=[{"template_id": "9", "slot": 0, "required": True}],
        trigger_ops=["AND"],
        function_templates=[{"template_id": "30", "slot": 0, "required": True}],
        ops=[],
        ret="pass",
        action="not_stop_sim",
        description="纵向急刹检测",
    ),
    MetricDef(
        id="3002",
        version=1,
        type_id="safety.collision",
        name="碰撞风险",
        level="S0",
        trigger_templates=[{"template_id": "9", "slot": 0, "required": True}],
        trigger_ops=["AND"],
        function_templates=[{"template_id": "30", "slot": 0, "required": True}],
        ret="fail",
        action="stop_sim",
        description="近碰与碰撞风险",
    ),
    MetricDef(
        id="1002",
        version=1,
        type_id="comfort.ride",
        name="加加速度",
        level="S1",
        trigger_templates=[{"template_id": "9", "slot": 0, "required": True}],
        trigger_ops=["AND"],
        function_templates=[{"template_id": "30", "slot": 0, "required": True}],
        ret="pass",
        action="not_stop_sim",
        description="舒适性冲击",
    ),
    MetricDef(
        id="4001",
        version=1,
        type_id="4001",
        name="平均车速",
        level="S2",
        trigger_templates=[{"template_id": "9", "slot": 0, "required": True}],
        trigger_ops=["AND"],
        function_templates=[{"template_id": "30", "slot": 0, "required": True}],
        ret="pass",
        action="not_stop_sim",
        description="通行效率",
    ),
]

def metric_config(level: str = "S0") -> dict[str, Any]:
    return {
        "trigger_functions": [
            {
                "name": "时间区间",
                "function_field_name": "时间区间",
                "template_id": "9",
                "env": {
                    "开始时间": {"field_name": "start_time", "value": "0", "is_number": False, "unit": ""},
                    "结束时间": {"field_name": "end_time", "value": "180", "is_number": False, "unit": ""},
                },
            }
        ],
        "trigger_ops": ["AND"],
        "functions": [
            {
                "name": "急刹",
                "function_field_name": "急刹",
                "template_id": "30",
                "env": {
                    "jerk一级阈值": {"field_name": "jerk1_threshold", "value": "-3", "is_number": True, "unit": ""},
                    "jerk二级阈值": {"field_name": "jerk2_threshold", "value": "-4", "is_number": True, "unit": ""},
                    "加速度阈值": {"field_name": "acc_threshold", "value": "-3", "is_number": True, "unit": ""},
                },
            }
        ],
        "ops": [],
        "ret": "pass",
        "action": "not_stop_sim",
        "level": level,
        "is_global": False,
    }



async def ensure_metrics(service: MetricService, principal: Principal) -> None:
    for item in METRIC_TYPES:
        try:
            await service.create_type(item, principal)
        except Exception:
            pass
    for item in METRIC_DEFS:
        try:
            await service.create_def(item, principal)
        except Exception:
            pass

async def ensure_quota(db: Database) -> None:
    await db.execute(
        """
        INSERT INTO project_quota(project,max_running_cases,reserved_high_priority,max_cpu,max_mem_gb,max_gpu)
        VALUES ('default',96,12,192,768,12)
        ON CONFLICT (project) DO UPDATE SET max_running_cases=96, reserved_high_priority=12,
          max_cpu=192, max_mem_gb=768, max_gpu=12
        """
    )



def write_raw_manifests(data_dir: Path, count: int = 6) -> list[str]:
    directory = data_dir / "sources" / "raw"
    directory.mkdir(parents=True, exist_ok=True)
    uris = []
    for index in range(count):
        path = directory / f"log-{index:02d}.json"
        payload = {
            "duration_ms": 180_000,
            "channels": [
                {"name": "camera_front", "type": "video", "fps": 15},
                {"name": "lidar_top", "type": "pointcloud", "fps": 10},
                {"name": "can", "type": "timeseries", "fps": 50},
                {"name": "ego_pose", "type": "pose", "fps": 20},
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        uris.append(f"sources/raw/log-{index:02d}.json")
    return uris



async def make_scenarios(
    service: ScenarioService,
    source_ids: list[str],
    principal: Principal,
    count: int,
    prefix: str = "场景",
) -> list[dict[str, Any]]:
    tags_pool = [["cut-in"], ["rain"], ["night"], ["pedestrian"], ["junction"], ["highway"]]
    scns = []
    for index in range(count):
        source_id = source_ids[index % len(source_ids)]
        entry = await service.create(
            ScenarioCreate(
                name=f"{prefix}-{index + 1:03d}",
                source={
                    "type": "record",
                    "log_id": source_id,
                    "log_uri": "",
                    "log_checksum": "sha256:demo",
                    "format": "rsclbag",
                },
                time_window={"start_ts": 0, "end_ts": 180000, "trigger_ts": 60000},
                metrics=[
                    {
                        "id": "3001",
                        "name": "急刹",
                        "desc": "",
                        "business_type": "dpc",
                        "run_mode": "async",
                        "level": "S0" if index % 4 else "S1",
                        "is_global": False,
                        **metric_config("S0" if index % 4 else "S1"),
                    }
                ],
                tags=tags_pool[index % len(tags_pool)],
                description=f"演示场景 {index + 1}，来自 {source_id}",
                project=principal.project,
            ),
            principal,
        )
        scns.append(entry)
    return scns



async def make_set(
    service: SetService,
    principal: Principal,
    name: str,
    scenarios: list[dict[str, Any]],
    freeze: bool,
) -> dict[str, Any]:
    members = [
        SetMember(scenario_id=item["scenario_id"], scenario_version=item["version"], sort_order=index)
        for index, item in enumerate(scenarios)
    ]
    created = await service.create(
        SetCreate(name=name, description="演示场景集", members=members, project=principal.project),
        principal,
    )
    if freeze:
        return await service.freeze(created["set_id"], principal)
    return created



async def make_sim_source(
    playback: PlaybackService,
    data_dir: Path,
    principal: Principal,
    task: dict[str, Any],
) -> str | None:
    root = data_dir / "outputs" / task["task_id"]
    if not root.exists():
        return None
    first = sorted(item for item in root.iterdir() if item.is_dir())[:1]
    if not first:
        return None
    uri = f"outputs/{task['task_id']}/{first[0].name}"
    source = await playback.create(
        DataSourceCreate(
            kind="sim_output",
            uri=uri,
            format="dir",
            project=principal.project,
            duration_ms=180_000,
            channels=[
                {"name": "camera_front", "type": "video", "fps": 15},
                {"name": "lidar_top", "type": "pointcloud", "fps": 10},
                {"name": "can", "type": "timeseries", "fps": 50},
                {"name": "ego_pose", "type": "pose", "fps": 20},
            ],
        ),
        principal,
    )
    await playback._build(source["source_id"])
    return source["source_id"]


