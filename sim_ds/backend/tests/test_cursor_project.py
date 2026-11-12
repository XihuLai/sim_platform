from pathlib import Path

import pytest
from backend.scenario.service import ScenarioService
from backend.scenario.sets import SetService
from backend.shared.auth import Principal
from backend.shared.db import Database
from backend.shared.errors import AppError
from backend.shared.files import FileStore
from backend.tests.helpers import make_scenario, seed_metric, set_payload


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
