"""ScenarioSet versioning, sharding and freeze publication."""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.models import SetCreate, SetDerive, SetUpdate
from backend.scenario.common import loads, row_time
from backend.scenario.set_snapshot import build_snapshot, check_project
from backend.scenario.set_support import SetSupport
from backend.shared.auth import Principal, audit
from backend.shared.canonical import decode_cursor, encode_cursor, utcnow
from backend.shared.db import Database, affected
from backend.shared.errors import AppError, conflict, not_found
from backend.shared.files import FileStore


class SetService(SetSupport):
    def __init__(self, db: Database, store: FileStore) -> None:
        self.db = db
        self.store = store

    # ---------------------------------------------------------------- reads
    async def list_items(
        self, principal: Principal, *, frozen: bool | None = None, cursor: str | None = None, page_size: int = 50
    ) -> dict[str, Any]:
        size = max(1, min(page_size, 200))
        params: dict[str, Any] = {"project": principal.project, "limit": size + 1}
        clauses = ["s.project=:project"]
        if frozen is not None:
            clauses.append("s.frozen=:frozen")
            params["frozen"] = frozen
        if cursor:
            parts = decode_cursor(cursor, 2)
            clauses.append("(s.created_at, s.id) < (to_timestamp(:ct), :cid)")
            params["ct"] = float(parts[0])
            params["cid"] = parts[1]
        rows = await self.db.fetch_all(
            f"""
            SELECT s.*, COALESCE(v.member_count,0) AS member_count
            FROM scenario_set s
            LEFT JOIN scenario_set_version v ON v.set_id=s.id AND v.version=s.current_version
            WHERE {' AND '.join(clauses)}
            ORDER BY s.created_at DESC, s.id DESC LIMIT :limit
            """,
            params,
        )
        has_more = len(rows) > size
        rows = rows[:size]
        items = [
            {
                **row,
                "created_at": row_time(row, "created_at"),
                "updated_at": row_time(row, "updated_at"),
            }
            for row in rows
        ]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = encode_cursor(f"{last['created_at'].timestamp():.6f}", last["id"])
        return {"items": items, "next_cursor": next_cursor}

    async def get(self, set_id: str, principal: Principal) -> dict[str, Any]:
        row = await self._set_row(set_id, principal.project)
        version = int(row["current_version"])
        vrow = await self._version_row(set_id, version)
        if vrow is None or vrow["publish_state"] != "published":
            raise AppError("VERSION_UNAVAILABLE", "场景集尚无已发布版本", status=409)
        snapshot = await self._read_snapshot(vrow, set_id, version)
        return {
            "set_id": row["id"],
            "version": version,
            "name": row["name"],
            "description": row["description"],
            "frozen": row["frozen"],
            "owner": row["owner"],
            "project": row["project"],
            "member_count": vrow["member_count"],
            "snapshot_sha": vrow["snapshot_sha"],
            "snapshot_uri": vrow["snapshot_uri"],
            "frozen_at": row_time(vrow, "frozen_at"),
            "created_at": row_time(row, "created_at"),
            "updated_at": row_time(row, "updated_at"),
            "shard_count": snapshot.get("shard_count", 0),
        }

    async def members(
        self,
        set_id: str,
        principal: Principal,
        *,
        version: int | None = None,
        cursor: str | None = None,
        page_size: int = 200,
    ) -> dict[str, Any]:
        row = await self._set_row(set_id, principal.project)
        target = version or int(row["current_version"])
        size = max(1, min(page_size, 500))
        params: dict[str, Any] = {"sid": set_id, "ver": target, "limit": size + 1}
        clauses = ["set_id=:sid", "set_version=:ver"]
        if cursor:
            parts = decode_cursor(cursor, 2)
            clauses.append("(sort_order, scenario_id) > (:order, :scn)")
            params["order"] = int(parts[0])
            params["scn"] = parts[1]
        rows = await self.db.fetch_all(
            f"""
            SELECT scenario_id, scenario_version, sort_order FROM scenario_set_member
            WHERE {' AND '.join(clauses)}
            ORDER BY sort_order, scenario_id LIMIT :limit
            """,
            params,
        )
        has_more = len(rows) > size
        rows = rows[:size]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = encode_cursor(last["sort_order"], last["scenario_id"])
        return {"items": rows, "next_cursor": next_cursor, "version": target}

    async def load_snapshot(
        self, set_id: str, version: int, principal: Principal, *, require_frozen: bool = True
    ) -> dict[str, Any]:
        row = await self._set_row(set_id, principal.project)
        vrow = await self._version_row(set_id, version)
        if vrow is None or vrow["publish_state"] != "published":
            raise AppError("VERSION_UNAVAILABLE", "场景集版本未发布", status=409)
        if require_frozen and vrow["frozen_at"] is None:
            raise AppError("SET_NOT_FROZEN", "仿真任务必须引用已冻结版本", status=422)
        payload = await self._read_snapshot(vrow, set_id, version)
        members: list[dict[str, Any]] = []
        if payload.get("shard_count"):
            for shard in payload.get("shards", []):
                shard_payload = loads(self.store.read_bytes(self.store.resolve(shard["uri"])).decode("utf-8"))
                members.extend(shard_payload.get("members", []))
        else:
            members = list(payload.get("members", []))
        members.sort(key=lambda item: (item["sort_order"], item["scenario_id"]))
        return {
            "set_id": row["id"],
            "name": row["name"],
            "version": version,
            "frozen": row["frozen"],
            "snapshot_sha": vrow["snapshot_sha"],
            "snapshot_uri": vrow["snapshot_uri"],
            "members": members,
            "member_count": len(members),
        }

    # --------------------------------------------------------------- writes
    async def create(self, payload: SetCreate, principal: Principal) -> dict[str, Any]:
        project = payload.project or principal.project
        check_project(principal, project)
        set_id = "set_" + utcnow().strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
        members = await self._normalize_members(payload.members, project)
        if not members:
            raise AppError("EMPTY_SET", "场景集不能为空", status=422)
        snapshot = build_snapshot(set_id, 1, payload.name, payload.description, project, principal.user, members, False)
        await self._insert_pending(set_id, project, principal, snapshot, expected=0)
        await self._publish_snapshot(snapshot)
        await self._finish_publish(set_id, 1, snapshot, principal, frozen=False, expected=0)
        return await self.get(set_id, principal)

    async def update(self, set_id: str, payload: SetUpdate, principal: Principal) -> dict[str, Any]:
        row = await self._set_row(set_id, principal.project)
        if row["frozen"]:
            raise conflict("SET_FROZEN", "冻结场景集不可修改，请派生新场景集")
        current = int(row["current_version"])
        if payload.version != current:
            raise conflict("VERSION_CONFLICT", "场景集已被更新", expected=payload.version, current=current)
        members = await self._normalize_members(payload.members, row["project"])
        if not members:
            raise AppError("EMPTY_SET", "场景集不能为空", status=422)
        version = current + 1
        snapshot = build_snapshot(set_id, version, payload.name, payload.description, row["project"], row["owner"], members, False)
        await self._insert_pending(set_id, row["project"], principal, snapshot, expected=current)
        await self._publish_snapshot(snapshot)
        await self._finish_publish(set_id, version, snapshot, principal, frozen=False, expected=current)
        return await self.get(set_id, principal)

    async def freeze(self, set_id: str, principal: Principal) -> dict[str, Any]:
        row = await self._set_row(set_id, principal.project)
        if row["frozen"]:
            raise conflict("SET_FROZEN", "场景集已冻结")
        current = int(row["current_version"])
        vrow = await self._version_row(set_id, current)
        if vrow is None:
            raise not_found("场景集版本", f"{set_id}@v{current}")
        members = await self.db.fetch_all(
            "SELECT scenario_id, scenario_version, sort_order FROM scenario_set_member "
            "WHERE set_id=:sid AND set_version=:ver ORDER BY sort_order, scenario_id",
            {"sid": set_id, "ver": current},
        )
        version = current + 1
        snapshot = build_snapshot(
            set_id, version, row["name"], row["description"], row["project"], row["owner"], members, True
        )
        await self._insert_pending(set_id, row["project"], principal, snapshot, expected=current)
        await self._publish_snapshot(snapshot)
        await self._finish_publish(set_id, version, snapshot, principal, frozen=True, expected=current)
        return await self.get(set_id, principal)

    async def derive(self, set_id: str, payload: SetDerive, principal: Principal) -> dict[str, Any]:
        row = await self._set_row(set_id, principal.project)
        members = await self.db.fetch_all(
            "SELECT scenario_id, scenario_version, sort_order FROM scenario_set_member "
            "WHERE set_id=:sid AND set_version=:ver ORDER BY sort_order, scenario_id",
            {"sid": set_id, "ver": row["current_version"]},
        )
        create = SetCreate(
            name=payload.name or f"{row['name']}-派生",
            description=row["description"],
            members=[{"scenario_id": m["scenario_id"], "scenario_version": m["scenario_version"], "sort_order": m["sort_order"]} for m in members],
            project=payload.project or row["project"],
        )
        return await self.create(create, principal)

    # ------------------------------------------------------------ internals
    async def _normalize_members(self, members: list[Any], project: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, member in enumerate(members):
            item = member.model_dump() if hasattr(member, "model_dump") else dict(member)
            sid = item["scenario_id"]
            if sid in seen:
                raise AppError("DUPLICATE_MEMBER", f"场景 {sid} 重复", status=422)
            seen.add(sid)
            scenario = await self.db.fetch_one(
                "SELECT current_version, project, status FROM scenario WHERE id=:id",
                {"id": sid},
            )
            if scenario is None:
                raise AppError("SCENARIO_NOT_FOUND", f"场景 {sid} 不存在", status=422)
            if scenario["project"] != project:
                raise AppError("PROJECT_MISMATCH", f"场景 {sid} 不属于项目 {project}", status=422)
            if scenario["status"] == "archived":
                raise AppError("SCENARIO_ARCHIVED", f"场景 {sid} 已归档，不能加入场景集", status=422)
            version = int(item.get("scenario_version") or 0) or int(scenario["current_version"])
            result.append(
                {"scenario_id": sid, "scenario_version": version, "sort_order": int(item.get("sort_order", index))}
            )
        result.sort(key=lambda item: (item["sort_order"], item["scenario_id"]))
        return result

    async def _insert_pending(
        self, set_id: str, project: str, principal: Principal, snapshot: dict[str, Any], *, expected: int
    ) -> None:
        async with self.db.session() as session:
            if expected == 0:
                await session.execute(
                    text(
                        "INSERT INTO scenario_set(id,name,description,current_version,frozen,owner,project) "
                        "VALUES (:id,:name,:desc,0,false,:owner,:project)"
                    ),
                    {
                        "id": set_id,
                        "name": snapshot["name"],
                        "desc": snapshot["description"],
                        "owner": principal.user,
                        "project": project,
                    },
                )
            await self._insert_version(session, set_id, snapshot, expected, principal)
            await self._insert_members(session, set_id, snapshot)
            await audit(session, principal, "set.publish_pending", "scenario_set", set_id, {"version": snapshot["version"]})
            await session.commit()

    async def _insert_version(
        self,
        session: AsyncSession,
        set_id: str,
        snapshot: dict[str, Any],
        expected: int,
        principal: Principal,
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO scenario_set_version(set_id,version,snapshot_uri,snapshot_sha,member_count,
                  frozen_at,publish_state,expected_version,created_by)
                VALUES (:sid,:ver,:uri,:sha,:count,NULL,'pending',:expected,:by)
                """
            ),
            {
                "sid": set_id,
                "ver": snapshot["version"],
                "uri": snapshot["snapshot_uri"],
                "sha": snapshot["checksum_self"],
                "count": len(snapshot["members"]),
                "expected": expected,
                "by": principal.user,
            },
        )

    async def _insert_members(
        self, session: AsyncSession, set_id: str, snapshot: dict[str, Any]
    ) -> None:
        await session.execute(
            text("DELETE FROM scenario_set_member WHERE set_id=:sid AND set_version=:ver"),
            {"sid": set_id, "ver": snapshot["version"]},
        )
        for member in snapshot["members"]:
            await session.execute(
                text(
                    "INSERT INTO scenario_set_member(set_id,set_version,scenario_id,scenario_version,sort_order) "
                    "VALUES (:sid,:ver,:scn,:sver,:order)"
                ),
                {
                    "sid": set_id,
                    "ver": snapshot["version"],
                    "scn": member["scenario_id"],
                    "sver": member["scenario_version"],
                    "order": member["sort_order"],
                },
            )

    async def _publish_snapshot(self, snapshot: dict[str, Any]) -> None:
        for shard in snapshot["shards"]:
            published = self.store.publish(shard["uri"], shard["payload"])
            if published.checksum != shard["file_checksum"]:
                raise AppError("CHECKSUM_MISMATCH", "场景集分片校验失败", status=409)
        output = snapshot["meta_payload"] if snapshot["sharded"] else snapshot["payload"]
        published = self.store.publish(snapshot["snapshot_uri"], output)
        if published.checksum != snapshot["file_checksum"]:
            raise AppError("CHECKSUM_MISMATCH", "场景集快照校验失败", status=409)

    async def _finish_publish(
        self,
        set_id: str,
        version: int,
        snapshot: dict[str, Any],
        principal: Principal,
        *,
        frozen: bool,
        expected: int,
    ) -> None:
        async with self.db.session() as session:
            await session.execute(
                text(
                    "UPDATE scenario_set_version SET publish_state='published', frozen_at="
                    "CASE WHEN :frozen THEN now() ELSE frozen_at END WHERE set_id=:sid AND version=:ver"
                ),
                {"sid": set_id, "ver": version, "frozen": frozen},
            )
            result = await session.execute(
                text(
                    "UPDATE scenario_set SET current_version=:ver, frozen=:frozen, updated_at=now() "
                    "WHERE id=:sid AND current_version=:expected"
                ),
                {"sid": set_id, "ver": version, "frozen": frozen, "expected": expected},
            )
            if not affected(result):
                await session.rollback()
                raise conflict("VERSION_CONFLICT", "场景集当前版本已变化，请刷新后重试")
            await audit(
                session,
                principal,
                "set.freeze" if frozen else "set.publish",
                "scenario_set",
                set_id,
                {"version": version},
            )
            await session.commit()

    async def _set_row(self, set_id: str, project: str) -> dict[str, Any]:
        row = await self.db.fetch_one(
            "SELECT * FROM scenario_set WHERE id=:id AND project=:project",
            {"id": set_id, "project": project},
        )
        if row is None:
            raise not_found("场景集", set_id)
        return row

    async def _version_row(self, set_id: str, version: int) -> dict[str, Any] | None:
        return await self.db.fetch_one(
            "SELECT * FROM scenario_set_version WHERE set_id=:sid AND version=:ver",
            {"sid": set_id, "ver": version},
        )

    async def _read_snapshot(self, vrow: dict[str, Any], set_id: str, version: int) -> dict[str, Any]:
        uri = vrow["snapshot_uri"]
        try:
            payload: dict[str, Any] = loads(self.store.read_bytes(self.store.resolve(uri)).decode("utf-8"))
        except AppError:
            await self.mark_unavailable(set_id, version)
            raise AppError("SNAPSHOT_UNAVAILABLE", "场景集快照文件缺失", status=409) from None
        if payload.get("checksum_self") != vrow["snapshot_sha"]:
            raise AppError("SNAPSHOT_CHECKSUM", "场景集快照校验失败", status=409)
        for shard in payload.get("shards", []):
            if not self.store.verify(shard["uri"], shard["file_checksum"]):
                raise AppError("SNAPSHOT_CHECKSUM", f"场景集分片 {shard['index']} 校验失败", status=409)
        return payload
