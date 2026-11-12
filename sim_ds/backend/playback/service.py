"""Playback data sources: extraction metadata, async indexing, chunk/frame reads."""

from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path
from typing import Any

from backend.domain.models import DataSourceCreate, ExtractRequest
from backend.playback.synth import chunk_payload, frame_svg
from backend.scenario.common import loads, row_time
from backend.shared.auth import Principal, audit
from backend.shared.canonical import sha256_json, utcnow
from backend.shared.db import Database, dumps
from backend.shared.errors import AppError, not_found
from backend.shared.files import FileStore
from sqlalchemy import text

CHANNEL_DEFAULT = {"video": 15, "pointcloud": 10, "timeseries": 50, "pose": 20}
CHUNK_MS = 2000


class PlaybackService:
    def __init__(self, db: Database, store: FileStore) -> None:
        self.db = db
        self.store = store
        self._tasks: set[asyncio.Task[None]] = set()

    def _spawn(self, source_id: str) -> None:
        task = asyncio.create_task(self._build(source_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --------------------------------------------------------------- sources
    async def list_items(self, principal: Principal, *, cursor: str | None = None, page_size: int = 50) -> dict[str, Any]:
        size = max(1, min(page_size, 200))
        params: dict[str, Any] = {"project": principal.project, "limit": size + 1}
        clauses = ["project=:project"]
        if cursor:
            from backend.shared.canonical import decode_cursor

            parts = decode_cursor(cursor, 2)
            clauses.append("(created_at, id) < (to_timestamp(:ct), :cid)")
            params["ct"] = float(parts[0])
            params["cid"] = parts[1]
        rows = await self.db.fetch_all(
            f"SELECT * FROM data_source WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC, id DESC LIMIT :limit",
            params,
        )
        has_more = len(rows) > size
        rows = rows[:size]
        items = [self._source_view(row) for row in rows]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            from backend.shared.canonical import encode_cursor

            next_cursor = encode_cursor(f"{last['created_at'].timestamp():.6f}", last["id"])
        return {"items": items, "next_cursor": next_cursor}

    async def extract(self, payload: ExtractRequest, principal: Principal) -> dict[str, Any]:
        project = payload.project or principal.project
        if project != principal.project and not principal.admin:
            raise AppError("FORBIDDEN", "无权访问该项目", status=403)
        manifest = self._read_manifest(payload.uri, payload.format)
        source_id = "src_" + utcnow().strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
        channels = manifest.get("channels", [])
        duration = int(manifest.get("duration_ms", 0))
        async with self.db.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO data_source(id,kind,uri,format,project,owner,duration_ms,channels,status)
                    VALUES (:id,'record',:uri,:format,:project,:owner,:duration,CAST(:channels AS JSONB),'pending')
                    """
                ),
                {
                    "id": source_id,
                    "uri": payload.uri,
                    "format": payload.format,
                    "project": project,
                    "owner": principal.user,
                    "duration": duration,
                    "channels": dumps(channels),
                },
            )
            await audit(session, principal, "source.extract", "data_source", source_id, {"uri": payload.uri})
            await session.commit()
        row = await self.db.fetch_one("SELECT * FROM data_source WHERE id=:id", {"id": source_id})
        assert row is not None
        return self._source_view(row)

    async def create(self, payload: DataSourceCreate, principal: Principal) -> dict[str, Any]:
        project = payload.project or principal.project
        if project != principal.project and not principal.admin:
            raise AppError("FORBIDDEN", "无权访问该项目", status=403)
        source_id = payload.source_id or "src_" + utcnow().strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
        channels = payload.channels or self._discover_channels(payload.uri, payload.format)
        duration = payload.duration_ms or 180_000
        async with self.db.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO data_source(id,kind,uri,format,project,owner,duration_ms,channels,status)
                    VALUES (:id,:kind,:uri,:format,:project,:owner,:duration,CAST(:channels AS JSONB),'pending')
                    ON CONFLICT (id) DO UPDATE SET uri=EXCLUDED.uri, channels=EXCLUDED.channels,
                      duration_ms=EXCLUDED.duration_ms, updated_at=now()
                    """
                ),
                {
                    "id": source_id,
                    "kind": payload.kind,
                    "uri": payload.uri,
                    "format": payload.format,
                    "project": project,
                    "owner": principal.user,
                    "duration": duration,
                    "channels": dumps(channels),
                },
            )
            await audit(session, principal, "source.create", "data_source", source_id)
            await session.commit()
        row = await self.db.fetch_one("SELECT * FROM data_source WHERE id=:id", {"id": source_id})
        assert row is not None
        return self._source_view(row)

    async def get(self, source_id: str, principal: Principal) -> dict[str, Any]:
        row = await self._row(source_id, principal)
        return self._source_view(row)

    async def channels(self, source_id: str, principal: Principal) -> dict[str, Any]:
        row = await self._row(source_id, principal)
        if row["status"] != "ready":
            return {"status": row["status"], "progress": row["progress"], "channels": []}
        index = self._index(row)
        return {"status": "ready", "progress": 100, "duration_ms": index["duration_ms"], "channels": index["channels"]}

    async def status(self, source_id: str, principal: Principal) -> dict[str, Any]:
        row = await self._row(source_id, principal)
        return self._source_view(row)

    # --------------------------------------------------------------- indexing
    async def index(self, source_id: str, principal: Principal) -> dict[str, Any]:
        row = await self._row(source_id, principal)
        if row["status"] == "ready":
            return self._source_view(row)
        moved = await self.db.execute(
            "UPDATE data_source SET status='indexing', progress=1, error=NULL, updated_at=now() "
            "WHERE id=:id AND status IN ('pending','failed')",
            {"id": source_id},
        )
        if moved:
            self._spawn(source_id)
            return {"source_id": source_id, "status": "indexing", "progress": 1, "accepted": True}
        current = await self._row(source_id, principal)
        return {**self._source_view(current), "accepted": False}

    async def recover_pending(self) -> int:
        rows = await self.db.fetch_all(
            "SELECT id FROM data_source WHERE status IN ('pending','indexing') ORDER BY created_at LIMIT 200"
        )
        for row in rows:
            await self.db.execute(
                "UPDATE data_source SET status='pending', progress=0, updated_at=now() "
                "WHERE id=:id AND status IN ('pending','indexing')",
                {"id": row["id"]},
            )
            await self.db.execute(
                "UPDATE data_source SET status='indexing', progress=1, updated_at=now() "
                "WHERE id=:id AND status='pending'",
                {"id": row["id"]},
            )
            self._spawn(row["id"])
        return len(rows)

    async def _build(self, source_id: str) -> None:
        row = await self.db.fetch_one("SELECT * FROM data_source WHERE id=:id", {"id": source_id})
        if row is None:
            return
        try:
            channels = loads(row["channels"]) or []
            if not channels:
                channels = self._discover_channels(row["uri"], row["format"])
            duration = int(row["duration_ms"]) or 180_000
            index_channels = []
            total = max(1, len(channels))
            for position, channel in enumerate(channels):
                built = self._build_channel(source_id, channel, duration)
                index_channels.append(built)
                progress = min(95, int((position + 1) * 90 / total) + 5)
                await self.db.execute(
                    "UPDATE data_source SET progress=:p, updated_at=now() WHERE id=:id",
                    {"id": source_id, "p": progress},
                )
            index = {
                "source_id": source_id,
                "kind": row["kind"],
                "format": row["format"],
                "duration_ms": duration,
                "channels": index_channels,
                "checksum_self": "",
            }
            index["checksum_self"] = sha256_json({k: v for k, v in index.items() if k != "checksum_self"})
            published = self.store.publish(f"sources/{source_id}/index.json", index)
            await self.db.execute(
                "UPDATE data_source SET status='ready', progress=100, index_uri=:uri, "
                "channels=CAST(:channels AS JSONB), duration_ms=:duration, updated_at=now() WHERE id=:id",
                {
                    "id": source_id,
                    "uri": published.uri,
                    "channels": dumps(index_channels),
                    "duration": duration,
                },
            )
        except Exception as exc:
            await self.db.execute(
                "UPDATE data_source SET status='failed', error=:error, updated_at=now() WHERE id=:id",
                {"id": source_id, "error": f"{type(exc).__name__}: {exc}"[:400]},
            )

    def _build_channel(self, source_id: str, channel: dict[str, Any], duration: int) -> dict[str, Any]:
        name = str(channel.get("name", "channel"))
        kind = str(channel.get("type", "timeseries"))
        fps = int(channel.get("fps") or CHANNEL_DEFAULT.get(kind, 10))
        chunks = []
        for index, start in enumerate(range(0, duration, CHUNK_MS)):
            end = min(duration, start + CHUNK_MS)
            payload = chunk_payload(name, kind, fps, start, end, channel)
            published = self.store.publish(f"sources/{source_id}/chunks/{name}/{index}.json", payload)
            chunks.append({"start_ms": start, "end_ms": end, "uri": published.uri, "index": index})
        return {"name": name, "type": kind, "fps": fps, "duration_ms": duration, "chunks": chunks}

    # ---------------------------------------------------------------- chunks
    async def chunk(
        self, source_id: str, channel: str, ts: int, span: int, principal: Principal
    ) -> dict[str, Any]:
        row = await self._row(source_id, principal)
        index = self._index(row)
        target = self._channel(index, channel)
        span = max(200, min(span, 10_000))
        end = ts + span
        matched = [item for item in target["chunks"] if item["end_ms"] > ts and item["start_ms"] < end]
        if not matched:
            raise AppError("CHUNK_NOT_FOUND", "时间点超出数据源范围", status=404)
        payloads = [loads(self.store.read_bytes(self.store.resolve(item["uri"]))) for item in matched]
        response: dict[str, Any] = {
            "source_id": source_id,
            "channel": channel,
            "type": target["type"],
            "fps": target["fps"],
            "start_ms": matched[0]["start_ms"],
            "end_ms": matched[-1]["end_ms"],
        }
        key = "samples" if target["type"] in {"timeseries", "pose"} else "frames"
        merged: list[Any] = []
        for payload in payloads:
            merged.extend(payload.get(key, []))
        response[key] = [item for item in merged if ts - 1000 <= item["ts"] <= end + 1000]
        if target["type"] == "pointcloud":
            response["frames"] = [
                item for item in response["frames"] if ts - CHUNK_MS <= item["ts"] <= end
            ]
        return response

    async def frame(
        self, source_id: str, channel: str, ts: int, index: int | None, principal: Principal
    ) -> dict[str, Any]:
        chunk = await self.chunk(source_id, channel, ts, CHUNK_MS, principal)
        frames = chunk.get("frames") or chunk.get("samples") or []
        if not frames:
            raise AppError("FRAME_NOT_FOUND", "该时间点没有帧", status=404)
        if index is not None and 0 <= index < len(frames):
            frame = frames[index]
        else:
            frame = min(frames, key=lambda item: abs(int(item["ts"]) - ts))
        if chunk["type"] == "video":
            return {"ts": frame["ts"], "type": "video", "objects": frame.get("objects", []), "svg": frame_svg(frame)}
        if chunk["type"] == "pointcloud":
            return {"ts": frame["ts"], "type": "pointcloud", "points": frame.get("points", [])}
        return {"ts": frame["ts"], "type": chunk["type"], "sample": frame}

    # ------------------------------------------------------------- internals
    async def _row(self, source_id: str, principal: Principal) -> dict[str, Any]:
        row = await self.db.fetch_one(
            "SELECT * FROM data_source WHERE id=:id AND project=:project",
            {"id": source_id, "project": principal.project},
        )
        if row is None:
            raise not_found("数据源", source_id)
        return row

    def _index(self, row: dict[str, Any]) -> dict[str, Any]:
        if row["status"] != "ready" or not row["index_uri"]:
            raise AppError(
                "INDEX_NOT_READY", "数据源索引尚未就绪", status=409, detail={"status": row["status"], "progress": row["progress"]}
            )
        payload: dict[str, Any] = loads(self.store.read_bytes(self.store.resolve(row["index_uri"])))
        return payload

    def _channel(self, index: dict[str, Any], channel: str) -> dict[str, Any]:
        for item in index.get("channels", []):
            if item["name"] == channel:
                found: dict[str, Any] = item
                return found
        raise AppError("CHANNEL_NOT_FOUND", f"通道 {channel} 不存在", status=404)

    def _source_view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": row["id"],
            "kind": row["kind"],
            "uri": row["uri"],
            "format": row["format"],
            "project": row["project"],
            "index_uri": row["index_uri"],
            "duration_ms": row["duration_ms"],
            "channels": loads(row["channels"]),
            "status": row["status"],
            "progress": row["progress"],
            "error": row["error"],
            "created_at": row_time(row, "created_at"),
        }

    def _read_manifest(self, uri: str, fmt: str) -> dict[str, Any]:
        path = self._local_path(uri)
        if path.is_dir():
            return {"duration_ms": 180_000, "channels": self._discover_channels(uri, "dir")}
        if path.exists() and (path.suffix == ".json" or fmt == "json"):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            return {
                "duration_ms": int(manifest.get("duration_ms", 180_000)),
                "channels": manifest.get("channels", []),
            }
        meta = path.with_suffix(path.suffix + ".meta.json")
        if meta.exists():
            manifest = json.loads(meta.read_text(encoding="utf-8"))
            return {"duration_ms": int(manifest.get("duration_ms", 0)), "channels": manifest.get("channels", [])}
        # Contract allows a metadata stub until real mcap/bag/parquet adapters land.
        return {"duration_ms": 180_000, "channels": [{"name": "raw", "type": "timeseries", "fps": 50}]}

    def _discover_channels(self, uri: str, fmt: str) -> list[dict[str, Any]]:
        path = self._local_path(uri)
        mapping = {
            ".mp4": "video",
            ".mkv": "video",
            ".avi": "video",
            ".pcd": "pointcloud",
            ".bin": "pointcloud",
            ".csv": "timeseries",
            ".json": "pose",
        }
        if path.is_dir():
            found = []
            for item in sorted(path.iterdir()):
                if item.is_file() and item.suffix.lower() in mapping:
                    kind = mapping[item.suffix.lower()]
                    found.append({"name": item.stem, "type": kind, "fps": CHANNEL_DEFAULT[kind]})
            return found or [{"name": "raw", "type": "timeseries", "fps": 50}]
        if path.suffix.lower() in mapping:
            kind = mapping[path.suffix.lower()]
            return [{"name": path.stem, "type": kind, "fps": CHANNEL_DEFAULT[kind]}]
        return [{"name": "raw", "type": "timeseries", "fps": 50}]

    def _local_path(self, uri: str) -> Path:
        path = Path(uri)
        if not path.is_absolute():
            path = self.store.resolve(uri)
        return path
