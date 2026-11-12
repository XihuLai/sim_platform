import copy

import pytest
from backend.domain.models import ScenarioMetricInstance
from backend.scenario.metrics import validate_instance, validate_structure
from backend.shared.db import Database
from backend.shared.errors import AppError
from backend.tests.helpers import METRIC_CONFIG


def instance(config: dict) -> ScenarioMetricInstance:
    return ScenarioMetricInstance(
        metric_def_id="safety.brake.hard", metric_def_ver=1, config=config
    )


def test_structure_rejects_empty_functions() -> None:
    with pytest.raises(AppError) as exc:
        validate_structure(instance({**METRIC_CONFIG, "functions": []}).config)
    assert exc.value.code == "METRIC_CONFIG_INVALID"
    assert exc.value.detail["path"] == "$.functions"


def test_structure_rejects_missing_template_and_env() -> None:
    broken = copy.deepcopy(METRIC_CONFIG)
    broken["functions"][0]["template_id"] = ""
    with pytest.raises(AppError):
        validate_structure(instance(broken).config)


async def test_dynamic_env_schema_valid(db: Database) -> None:
    async with db.session() as session:
        await validate_instance(session, instance(METRIC_CONFIG))


async def test_dynamic_env_rejects_bad_threshold_type(db: Database) -> None:
    broken = copy.deepcopy(METRIC_CONFIG)
    del broken["functions"][0]["env"]["加速度阈值"]
    async with db.session() as session:
        with pytest.raises(AppError) as exc:
            await validate_instance(session, instance(broken))
    assert exc.value.code == "METRIC_CONFIG_INVALID"
    assert "functions" in exc.value.detail["path"]


async def test_template_kind_must_match(db: Database) -> None:
    broken = copy.deepcopy(METRIC_CONFIG)
    broken["functions"][0]["template_id"] = "9"
    async with db.session() as session:
        with pytest.raises(AppError) as exc:
            await validate_instance(session, instance(broken))
    assert "不是 function" in exc.value.detail["reason"]
