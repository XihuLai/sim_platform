"""Shared builders for PostgreSQL integration tests."""

from __future__ import annotations

from typing import Any

from backend.domain.models import (
    RuntimeConfig,
    ScenarioCreate,
    ScenarioMetricInstance,
    SetCreate,
    SetMember,
    SimTaskCreate,
)
from backend.scenario.common import loads
from backend.shared.auth import Principal
from backend.shared.db import Database, dumps

METRIC_CONFIG = {
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
    "level": "S0",
    "is_global": False,
}


async def seed_metric(db: Database) -> None:
    await db.execute(
        "INSERT INTO metric_type(id,category_id,name,sort_order) VALUES ('safety.brake','safety','制动',1) "
        "ON CONFLICT DO NOTHING"
    )
    await db.execute(
        """
        INSERT INTO metric_def(id,version,type_id,name,level,business_type,trigger_templates,trigger_ops,
          function_templates,ops,ret,action,description)
        VALUES ('safety.brake.hard',1,'safety.brake','急刹','S0','dpc',CAST(:tt AS JSONB),CAST(:to AS JSONB),
          CAST(:ft AS JSONB),CAST(:ops AS JSONB),'pass','not_stop_sim','test')
        ON CONFLICT DO NOTHING
        """,
        {
            "tt": dumps([{"template_id": "9", "slot": 0, "required": True}]),
            "to": dumps(["AND"]),
            "ft": dumps([{"template_id": "30", "slot": 0, "required": True}]),
            "ops": dumps([]),
        },
    )


def scenario_payload(name: str = "场景A", project: str = "default") -> ScenarioCreate:
    return ScenarioCreate(
        name=name,
        project=project,
        source={"type": "record", "log_id": "log-1", "format": "mcap"},
        time_window={"start_ts": 0, "end_ts": 180000, "trigger_ts": 60000},
        metrics=[
            ScenarioMetricInstance(
                metric_def_id="safety.brake.hard", metric_def_ver=1, config=METRIC_CONFIG
            )
        ],
        tags=["junction"],
        description="集成测试场景",
    )


async def make_scenario(service: Any, principal: Principal, name: str = "场景A") -> dict[str, Any]:
    return await service.create(scenario_payload(name), principal)


def set_payload(scenarios: list[dict[str, Any]], name: str = "回归集") -> SetCreate:
    return SetCreate(
        name=name,
        description="集成测试集",
        members=[
            SetMember(scenario_id=item["scenario_id"], scenario_version=item["version"], sort_order=index)
            for index, item in enumerate(scenarios)
        ],
    )


def runtime(config: RuntimeConfig | None = None) -> RuntimeConfig:
    return config or RuntimeConfig(
        binary_id="log-resim",
        args=["--scenario", "${SCENARIO_URI}", "--out", "${OUTPUT_DIR}"],
        env={"SIM_SEED": "11"},
        resource={"cpu": 1, "mem_gb": 1, "gpu": 0},
        timeout_sec=30,
        retry={"max": 1, "on": ["timeout", "worker_lost"]},
    )


def task_payload(set_info: dict[str, Any], name: str = "任务A") -> SimTaskCreate:
    return SimTaskCreate(
        name=name,
        set_id=set_info["set_id"],
        set_version=set_info["version"],
        runtime=runtime(),
        metrics=["safety.brake.hard"],
        seed=11,
    )


def jsonb(value: Any) -> Any:
    return loads(dumps(value))
