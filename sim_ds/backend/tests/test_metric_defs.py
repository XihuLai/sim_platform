from backend.domain.models import MetricDef
from backend.scenario.metrics_service import MetricService
from backend.shared.auth import Principal
from backend.shared.db import Database
from backend.tests.helpers import METRIC_CONFIG, seed_metric


async def test_metric_definition_stores_rule_json(
    db: Database, principal: Principal
) -> None:
    await seed_metric(db)
    service = MetricService(db)
    body = MetricDef(
        id="safety.test.json",
        version=1,
        type_id="safety.brake",
        name="JSON 指标",
        level="S0",
        trigger_functions=METRIC_CONFIG["trigger_functions"],
        trigger_ops=["AND"],
        functions=METRIC_CONFIG["functions"],
        ops=[],
        ret="pass",
        action="not_stop_sim",
    )
    created = await service.create_def(body, principal)
    assert created["trigger_functions"][0]["template_id"] == "9"
    assert created["functions"][0]["template_id"] == "30"
    assert created["trigger_templates"][0]["template_id"] == "9"
    assert created["function_templates"][0]["template_id"] == "30"
    assert "type_name" not in created
    assert "category_name" not in created

    loaded = await service.get_def("safety.test.json", 1)
    assert loaded["functions"][0]["env"]["加速度阈值"]["value"] == "-3"

    updated = await service.update_def(
        "safety.test.json", body.model_copy(update={"name": "JSON 指标 v2"}), principal
    )
    assert updated["version"] == 2
    assert updated["name"] == "JSON 指标 v2"

    await service.delete_def("safety.test.json", principal)
    active = await service.defs()
    assert all(item["id"] != "safety.test.json" for item in active)
    assert (await service.get_def("safety.test.json", 2))["status"] == "deprecated"


async def test_metric_id_allocated_in_safety_range(db: Database, principal: Principal) -> None:
    await seed_metric(db)
    service = MetricService(db)
    created = await service.create_def(
        MetricDef(id="", version=1, type_id="safety.brake", name="自动编号"),
        principal,
    )
    assert created["id"] == "3002"
