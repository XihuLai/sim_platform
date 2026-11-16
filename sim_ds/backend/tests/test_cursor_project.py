from pathlib import Path

import pytest
from backend.scenario.service import ScenarioService
from backend.scenario.sets import SetService
from backend.shared.auth import Principal
from backend.shared.db import Database
from backend.shared.errors import AppError
from backend.shared.files import FileStore
from backend.tests.helpers import make_scenario, scenario_payload, seed_metric, set_payload


async def test_scenario_cursor_has_no_overlap(db: Database, tmp_path: Path, principal: Principal) -> None:
    await seed_metric(db)
    service = ScenarioService(db, FileStore(tmp_path))
    for index in range(3):
        await make_scenario(service, principal, f"场景-{index}")
    first = await service.list_items(principal, page_size=2)
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = await service.list_items(principal, page_size=2, cursor=first["next_cursor"])
    assert len(second["items"]) == 1
    ids = {item["id"] for item in first["items"]}
    assert not ids & {item["id"] for item in second["items"]}


async def test_set_member_cursor(db: Database, tmp_path: Path, principal: Principal) -> None:
    await seed_metric(db)
    store = FileStore(tmp_path)
    scenarios = ScenarioService(db, store)
    sets = SetService(db, store)
    members = [await make_scenario(scenarios, principal, f"场景-{index}") for index in range(3)]
    created = await sets.create(set_payload(members), principal)
    first = await sets.members(created["set_id"], principal, page_size=2)
    second = await sets.members(created["set_id"], principal, page_size=2, cursor=first["next_cursor"])
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert {row["scenario_id"] for row in first["items"]}.isdisjoint(
        {row["scenario_id"] for row in second["items"]}
    )


async def test_other_project_cannot_read_scenario_or_set(
    db: Database, tmp_path: Path, principal: Principal
) -> None:
    await seed_metric(db)
    store = FileStore(tmp_path)
    scenarios = ScenarioService(db, store)
    sets = SetService(db, store)
    created = await make_scenario(scenarios, principal)
    set_info = await sets.create(set_payload([created]), principal)
    other = Principal(user="other", project="other", projects=("other",), admin=False)
    with pytest.raises(AppError) as scenario_error:
        await scenarios.get(created["scenario_id"], other)
    assert scenario_error.value.status == 404
    with pytest.raises(AppError) as set_error:
        await sets.get(set_info["set_id"], other)
    assert set_error.value.status == 404


async def test_multi_tag_and_or_filter(db: Database, tmp_path: Path, principal: Principal) -> None:
    await seed_metric(db)
    service = ScenarioService(db, FileStore(tmp_path))
    first = scenario_payload("多标签-A")
    first.tags = ["cut-in", "rain"]
    second = scenario_payload("多标签-B")
    second.tags = ["rain", "night"]
    created_first = await service.create(first, principal)
    created_second = await service.create(second, principal)

    and_result = await service.list_items(principal, tags=["cut-in", "rain"], tag_mode="and")
    assert [item["id"] for item in and_result["items"]] == [created_first["id"]]

    or_result = await service.list_items(principal, tags=["cut-in", "night"], tag_mode="or")
    assert {item["id"] for item in or_result["items"]} == {
        created_first["id"],
        created_second["id"],
    }


async def test_tag_expression_with_three_tags(db: Database, tmp_path: Path, principal: Principal) -> None:
    await seed_metric(db)
    service = ScenarioService(db, FileStore(tmp_path))
    ids: dict[str, str] = {}
    for name, tags in [
        ("AB", ["A", "B"]),
        ("C", ["C"]),
        ("A", ["A"]),
        ("BC", ["B", "C"]),
    ]:
        payload = scenario_payload(f"表达式-{name}")
        payload.tags = tags
        ids[name] = (await service.create(payload, principal))["id"]

    result = await service.list_items(principal, tag_expr="A&B|C")
    found = {item["id"] for item in result["items"]}
    assert found == {ids["AB"], ids["C"], ids["BC"]}
    assert ids["A"] not in found

    with pytest.raises(AppError) as exc:
        await service.list_items(principal, tag_expr="A&")
    assert exc.value.code == "INVALID_TAG_EXPR"
