"""ScenarioSet publication recovery helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.scenario.common import loads
from backend.shared.db import Database
from backend.shared.errors import AppError
from backend.shared.files import FileStore


class SetSupport:
    db: Database
    store: FileStore

    async def recover_pending(self) -> dict[str, int]:
        rows = await self.db.fetch_all(
            "SELECT * FROM scenario_set_version WHERE publish_state='pending' ORDER BY created_at"
        )
        completed = failed = 0
        for row in rows:
            try:
                payload = loads(self.store.read_bytes(self.store.resolve(row["snapshot_uri"])).decode("utf-8"))
            except AppError:
                payload = {}
            if payload.get("checksum_self") == row["snapshot_sha"]:
                await self._mark_published(row)
                completed += 1
            else:
                await self.db.execute(
                    "UPDATE scenario_set_version SET publish_state='failed' WHERE set_id=:sid AND version=:ver",
                    {"sid": row["set_id"], "ver": row["version"]},
                )
                failed += 1
        return {"completed": completed, "failed": failed}

    async def mark_unavailable(self, set_id: str, version: int) -> None:
        await self.db.execute(
            "UPDATE scenario_set_version SET publish_state='unavailable' WHERE set_id=:sid AND version=:ver",
            {"sid": set_id, "ver": version},
        )

    async def _mark_published(self, row: dict[str, Any]) -> None:
        try:
            payload = loads(self.store.read_bytes(self.store.resolve(row["snapshot_uri"])).decode("utf-8"))
        except AppError:
            payload = {}
        frozen = bool(payload.get("frozen")) or bool(row["frozen_at"])
        async with self.db.session() as session:
            await session.execute(
                text(
                    "UPDATE scenario_set_version SET publish_state='published', snapshot_uri=:uri, frozen_at="
                    "CASE WHEN :frozen THEN COALESCE(frozen_at, now()) ELSE frozen_at END "
                    "WHERE set_id=:sid AND version=:ver"
                ),
                {
                    "sid": row["set_id"],
                    "ver": row["version"],
                    "frozen": frozen,
                    "uri": self.store.canonical_uri(row["snapshot_uri"]),
                },
            )
            await session.execute(
                text(
                    "UPDATE scenario_set SET current_version=GREATEST(current_version,:ver), frozen=:frozen, "
                    "visibility=COALESCE(:visibility, visibility) WHERE id=:sid"
                ),
                {
                    "sid": row["set_id"],
                    "ver": row["version"],
                    "frozen": frozen,
                    "visibility": payload.get("visibility"),
                },
            )
            await session.commit()
