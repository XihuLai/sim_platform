import time
from pathlib import Path

from backend.domain.models import DataSourceCreate
from backend.playback.service import PlaybackService
from backend.shared.auth import Principal
from backend.shared.db import Database
from backend.shared.files import FileStore


async def test_source_index_chunk_and_frame_seek(
    db: Database, tmp_path: Path, principal: Principal
) -> None:
    store = FileStore(tmp_path)
    playback = PlaybackService(db, store)
    source = await playback.create(
        DataSourceCreate(
            kind="sim_output",
            uri="outputs/task-1/run-1",
            format="dir",
            duration_ms=10_000,
            channels=[
                {"name": "camera_front", "type": "video", "fps": 10},
                {"name": "can", "type": "timeseries", "fps": 20},
            ],
        ),
        principal,
    )
    await playback._build(source["source_id"])
    channels = await playback.channels(source["source_id"], principal)
    assert channels["status"] == "ready"
    assert {item["name"] for item in channels["channels"]} == {"camera_front", "can"}

    started = time.monotonic()
    chunk = await playback.chunk(source["source_id"], "can", 5000, 1000, principal)
    elapsed = time.monotonic() - started
    assert chunk["samples"] and chunk["type"] == "timeseries"
    assert elapsed < 0.5

    frame = await playback.frame(source["source_id"], "camera_front", 5000, None, principal)
    assert frame["type"] == "video" and frame["objects"]
    assert "<svg" in frame["svg"]
