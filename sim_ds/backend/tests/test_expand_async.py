from pathlib import Path

from backend.domain.models import SetCreate, SetMember
from backend.scenario.sets import SetService
from backend.shared.auth import Principal
from backend.shared.db import Database
from backend.shared.files import FileStore
from backend.sim.expander import Expander
from backend.sim.service import TaskService
from backend.tests.helpers import task_payload


async def insert_scenarios(db: Database, count: int, project: str = "default") -> list[str]:
    ids = [f"scn_bulk_{index:04d}" for index in range(count)]
    rows = [
        {
            "id": scenario_id,
            "name": f"批量场景 {index}",
            "project": project,
            "uri": f"scenarios/{scenario_id}/v1.json",
            "sha": f"sha256:{index:064x}",
        }
        for index, scenario_id in enumerate(ids)
    ]
    await db.executemany(
        """
        INSERT INTO scenario(id,name,current_version,source_type,file_uri,file_checksum,project,status)
        VALUES (:id,:name,1,'record',:uri,:sha,:project,'active')
        ON CONFLICT DO NOTHING
        """,
        rows,
    )
    return ids


async def test_501_cases_expand_asynchronously_once(
    db: Database, tmp_path: Path, principal: Principal
) -> None:
    store = FileStore(tmp_path)
    sets = SetService(db, store)
    ids = await insert_scenarios(db, 501)
    created = await sets.create(
        SetCreate(
            name="大批量集合",
            description="",
            members=[SetMember(scenario_id=sid, scenario_version=1, sort_order=index) for index, sid in enumerate(ids)],
        ),
        principal,
    )
    frozen = await sets.freeze(created["set_id"], principal)
    tasks = TaskService(db, sets, sync_limit=500)
    submitted = await tasks.submit(task_payload({"set_id": frozen["set_id"], "version": frozen["version"]}), principal)
    assert submitted["status"] == "expanding"
    assert submitted["total_cases"] == 0

    expander = Expander(db, sets, batch=1000)
    assert await expander.step() == 501
    again = await expander.step()
    assert again == 0

    cursor = await db.fetch_one("SELECT last_offset FROM task_expand_cursor WHERE task_id=:tid", {"tid": submitted["task_id"]})
    assert cursor is not None and cursor["last_offset"] == 501
    count = await db.fetch_one("SELECT COUNT(*) AS n, COUNT(DISTINCT scenario_id) AS d FROM case_run WHERE task_id=:tid", {"tid": submitted["task_id"]})
    assert count is not None and count["n"] == 501 and count["d"] == 501
    summary = await db.fetch_one("SELECT total, queued FROM task_summary WHERE task_id=:tid", {"tid": submitted["task_id"]})
    assert summary is not None and summary["total"] == 501 and summary["queued"] == 501
    task = await tasks.get(submitted["task_id"], principal)
    assert task["status"] == "queued" and task["total_cases"] == 501
