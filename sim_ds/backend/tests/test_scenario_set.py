from pathlib import Path

import pytest
from backend.domain.models import ScenarioUpdate, SetDerive, SetUpdate
from backend.scenario.service import ScenarioService
from backend.scenario.sets import SetService
from backend.shared.auth import Principal
from backend.shared.db import Database
from backend.shared.errors import AppError
from backend.shared.files import FileStore
from backend.tests.helpers import METRIC_CONFIG, make_scenario, seed_metric, set_payload


async def test_scenario_version_publish_and_conflict(db: Database, tmp_path: Path, principal: Principal) -> None:
    await seed_metric(db)
    store = FileStore(tmp_path)
    service = ScenarioService(db, store)
    created = await make_scenario(service, principal)
    assert created["version"] == 1
    assert store.verify(f"scenarios/{created['scenario_id']}/v1.json", created["file_checksum"])

    stale = ScenarioUpdate(
        name="改名",
        version=1,
        source={"type": "record", "log_id": "log-1", "format": "mcap"},
        time_window={"start_ts": 0, "end_ts": 180000, "trigger_ts": 60000},
        metrics=[
            {
                "metric_def_id": "safety.brake.hard",
                "metric_def_ver": 1,
                "config": METRIC_CONFIG,
            }
        ],
    )
    updated = await service.update(created["scenario_id"], stale, principal)
    assert updated["version"] == 2
    with pytest.raises(AppError) as exc:
        await service.update(created["scenario_id"], stale, principal)
    assert exc.value.code == "VERSION_CONFLICT"

    versions = await service.versions(created["scenario_id"], principal)
    assert [item["version"] for item in versions] == [2, 1]


async def test_missing_file_marks_version_unavailable(db: Database, tmp_path: Path, principal: Principal) -> None:
    await seed_metric(db)
    store = FileStore(tmp_path)
    service = ScenarioService(db, store)
    created = await make_scenario(service, principal)
    store.resolve(f"scenarios/{created['scenario_id']}/v1.json").unlink()
    with pytest.raises(AppError) as exc:
        await service.get(created["scenario_id"], principal)
    assert exc.value.code == "VERSION_UNAVAILABLE"
    row = await db.fetch_one(
        "SELECT publish_state FROM scenario_version WHERE scenario_id=:sid",
        {"sid": created["scenario_id"]},
    )
    assert row is not None and row["publish_state"] == "unavailable"


async def test_set_freeze_derive_and_immutability(db: Database, tmp_path: Path, principal: Principal) -> None:
    await seed_metric(db)
    store = FileStore(tmp_path)
    scenarios = ScenarioService(db, store)
    sets = SetService(db, store)
    first = await make_scenario(scenarios, principal, "场景A")
    second = await make_scenario(scenarios, principal, "场景B")
    created = await sets.create(set_payload([first, second]), principal)
    assert created["version"] == 1 and created["frozen"] is False

    frozen = await sets.freeze(created["set_id"], principal)
    assert frozen["frozen"] is True and frozen["member_count"] == 2
    snapshot = await sets.load_snapshot(created["set_id"], frozen["version"], principal, require_frozen=True)
    assert [item["scenario_id"] for item in snapshot["members"]] == [first["scenario_id"], second["scenario_id"]]

    with pytest.raises(AppError) as exc:
        await sets.update(
            created["set_id"],
            SetUpdate(name="x", description="", version=frozen["version"], members=[]),
            principal,
        )
    assert exc.value.code == "SET_FROZEN"

    derived = await sets.derive(created["set_id"], SetDerive(name="派生"), principal)
    assert derived["set_id"] != created["set_id"]
    assert derived["frozen"] is False
