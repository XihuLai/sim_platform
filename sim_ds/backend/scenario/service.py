"""Scenario aggregate service: immutable version publication and recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.models import ScenarioCreate, ScenarioUpdate
from backend.scenario.common import ensure_version_payload, row_time, scenario_uri
from backend.scenario.scenario_support import ScenarioSupport
from backend.scenario.tag_expr import build_tag_sql, parse_tag_expr
from backend.shared.auth import Principal, audit
from backend.shared.canonical import sha256_json, utcnow
from backend.shared.db import Database, affected, dumps
from backend.shared.errors import AppError, conflict, not_found
from backend.shared.files import FileStore


class ScenarioService(ScenarioSupport):
    def __init__(self, db: Database, store: FileStore) -> None:
        self.db = db
        self.store = store

    # ---------------------------------------------------------------- reads
    async def list_items(
        self,
        principal: Principal,
        *,
        search: str = "",
        tag: str = "",
        tags: list[str] | None = None,
        tag_expr: str = "",
        tag_mode: str = "or",
        status: str = "active",
        cursor: str | None = None,
        page_size: int = 50,
    ) -> dict[str, Any]:
        size = max(1, min(page_size, 200))
        params: dict[str, Any] = {"project": principal.project, "limit": size + 1, "search": f"%{search}%"}
        clauses = ["s.project = :project"]
        if status != "all":
            clauses.append("s.status = :status")
            params["status"] = status
        if search:
            clauses.append("(s.name ILIKE :search OR s.id ILIKE :search)")
        if tag_expr.strip():
            clauses.append(build_tag_sql(parse_tag_expr(tag_expr), params))
        else:
            selected_tags = [item.strip() for item in (tags or []) if item.strip()]
            if tag.strip() and tag.strip() not in selected_tags:
                selected_tags.append(tag.strip())
            if selected_tags:
                params["tag_filter"] = self.db.text_array(selected_tags)
                if tag_mode == "and":
                    clauses.append(
                        "(SELECT COUNT(DISTINCT t2.name) FROM scenario_tag st2 "
                        "JOIN tag t2 ON t2.id=st2.tag_id WHERE st2.scenario_id=s.id "
                        "AND t2.name = ANY(CAST(:tag_filter AS TEXT[]))) = :tag_count"
                    )
                    params["tag_count"] = len(selected_tags)
                else:
                    clauses.append(
                        "EXISTS (SELECT 1 FROM scenario_tag st2 JOIN tag t2 ON t2.id=st2.tag_id "
                        "WHERE st2.scenario_id=s.id AND t2.name = ANY(CAST(:tag_filter AS TEXT[])))"
                    )
        if cursor:
            parts = _cursor_parts(cursor)
            clauses.append("(s.created_at, s.id) < (to_timestamp(:ct), :cid)")
            params["ct"] = float(parts[0])
            params["cid"] = parts[1]
        sql = f"""
            SELECT s.*, COALESCE(array_agg(DISTINCT t.name) FILTER (WHERE t.name IS NOT NULL), '{{}}') AS tags
            FROM scenario s
            LEFT JOIN scenario_tag st ON st.scenario_id = s.id
            LEFT JOIN tag t ON t.id = st.tag_id
            WHERE {' AND '.join(clauses)}
            GROUP BY s.id
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT :limit
        """
        rows = await self.db.fetch_all(sql, params)
        has_more = len(rows) > size
        rows = rows[:size]
        items = [self._list_item(row) for row in rows]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = _encode_time_cursor(last["created_at"], last["id"])
        return {"items": items, "next_cursor": next_cursor}

    async def tags(self, principal: Principal, *, search: str = "", page_size: int = 200) -> list[dict[str, Any]]:
        size = max(1, min(page_size, 500))
        rows = await self.db.fetch_all(
            """
            SELECT t.id, t.name, t.category, COUNT(DISTINCT st.scenario_id) AS usage
            FROM tag t
            JOIN scenario_tag st ON st.tag_id=t.id
            JOIN scenario s ON s.id=st.scenario_id
            WHERE s.project=:project AND t.name ILIKE :search
            GROUP BY t.id, t.name, t.category
            ORDER BY usage DESC, t.name
            LIMIT :limit
            """,
            {"project": principal.project, "search": f"%{search}%", "limit": size},
        )
        return rows

    async def get(self, scenario_id: str, principal: Principal, version: int | None = None) -> dict[str, Any]:
        row = await self._scenario_row(scenario_id, principal.project)
        target = version or int(row["current_version"])
        if target <= 0:
            raise AppError("VERSION_UNAVAILABLE", "场景尚无已发布版本", status=409)
        vrow = await self._version_row(scenario_id, target)
        if vrow is None or vrow["publish_state"] != "published":
            raise not_found("场景版本", f"{scenario_id}@v{target}")
        try:
            payload = self._read_verified(vrow)
        except AppError:
            await self.mark_unavailable(scenario_id, target)
            raise
        if isinstance(payload.get("source"), dict):
            payload["source"].pop("extract", None)
        await self._normalize_metrics(payload)
        payload["id"] = scenario_id
        payload["scenario_id"] = scenario_id
        payload["tags"] = await self._scenario_tags(scenario_id)
        payload["status"] = row["status"]
        payload["file_checksum"] = vrow["file_checksum"]
        payload["publish_state"] = vrow["publish_state"]
        return payload

    async def versions(self, scenario_id: str, principal: Principal) -> list[dict[str, Any]]:
        await self._scenario_row(scenario_id, principal.project)
        rows = await self.db.fetch_all(
            """
            SELECT version, file_uri, file_checksum, publish_state, expected_version, created_at, change_note
            FROM scenario_version WHERE scenario_id=:sid ORDER BY version DESC
            """,
            {"sid": scenario_id},
        )
        return [{**row, "created_at": row_time(row, "created_at")} for row in rows]

    async def template_usage(self, template_id: str, principal: Principal) -> list[dict[str, Any]]:
        rows = await self.db.fetch_all(
            """
            SELECT s.id, s.name, s.current_version
            FROM scenario s
            JOIN scenario_metric m ON m.scenario_id = s.id
            WHERE s.project=:project
              AND m.config @> CAST(:needle AS JSONB)
            ORDER BY s.updated_at DESC
            """,
            {"project": principal.project, "needle": dumps({"functions": [{"template_id": template_id}]})},
        )
        return rows

    # --------------------------------------------------------------- writes
    async def create(self, payload: ScenarioCreate, principal: Principal) -> dict[str, Any]:
        project = payload.project or principal.project
        if project != principal.project and not principal.admin:
            raise AppError("FORBIDDEN", "无权在该项目创建场景", status=403)
        scenario_id = "scn_" + utcnow().strftime("%Y%m%d%H%M%S") + _suffix()
        now = utcnow()
        document = {
            "scenario_id": scenario_id,
            "name": payload.name,
            "version": 1,
            "source": payload.source.model_dump(mode="json"),
            "time_window": payload.time_window.model_dump(mode="json"),
            "metrics": [m.model_dump(mode="json") for m in payload.metrics],
            "tags": payload.tags,
            "description": payload.description,
            "extra": payload.extra,
            "project": project,
            "owner": principal.user,
            "status": "active",
            "created_by": principal.user,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        ensure_version_payload(document)
        checksum = sha256_json(document)
        uri = scenario_uri(scenario_id, 1)
        await self._insert_pending(scenario_id, document, checksum, uri, expected=0, principal=principal)
        published = self.store.publish(uri, document)
        await self._finish_publish(scenario_id, 1, published.checksum, principal, expected=0)
        return await self.get(scenario_id, principal, 1)

    async def update(
        self, scenario_id: str, payload: ScenarioUpdate, principal: Principal
    ) -> dict[str, Any]:
        row = await self._scenario_row(scenario_id, principal.project)
        current = int(row["current_version"])
        if payload.version != current:
            raise conflict(
                "VERSION_CONFLICT",
                "场景已被其他编辑更新，请刷新后重试",
                expected=payload.version,
                current=current,
            )
        version = current + 1
        now = utcnow()
        document = {
            "scenario_id": scenario_id,
            "name": payload.name,
            "version": version,
            "source": payload.source.model_dump(mode="json"),
            "time_window": payload.time_window.model_dump(mode="json"),
            "metrics": [m.model_dump(mode="json") for m in payload.metrics],
            "tags": payload.tags,
            "description": payload.description,
            "extra": payload.extra,
            "project": row["project"],
            "owner": row["owner"],
            "status": row["status"],
            "created_by": row.get("created_by") or row.get("owner") or principal.user,
            "created_at": row_time(row, "created_at"),
            "updated_at": now.isoformat(),
        }
        ensure_version_payload(document)
        checksum = sha256_json(document)
        uri = scenario_uri(scenario_id, version)
        await self._insert_pending(scenario_id, document, checksum, uri, expected=current, principal=principal)
        published = self.store.publish(uri, document)
        await self._finish_publish(scenario_id, version, published.checksum, principal, expected=current)
        return await self.get(scenario_id, principal, version)

    async def archive(self, scenario_id: str, principal: Principal, *, hard: bool = False) -> dict[str, Any]:
        await self._scenario_row(scenario_id, principal.project)
        frozen = await self.db.fetch_one(
            """
            SELECT 1 FROM scenario_set_member m
            JOIN scenario_set_version v ON v.set_id=m.set_id AND v.version=m.set_version
            WHERE m.scenario_id=:sid AND v.frozen_at IS NOT NULL LIMIT 1
            """,
            {"sid": scenario_id},
        )
        if frozen:
            raise conflict("SCENARIO_REFERENCED", "场景被冻结场景集引用，不能删除")
        async with self.db.session() as session:
            if hard:
                await session.execute(text("DELETE FROM scenario_metric WHERE scenario_id=:sid"), {"sid": scenario_id})
                await session.execute(text("DELETE FROM scenario_tag WHERE scenario_id=:sid"), {"sid": scenario_id})
                await session.execute(text("DELETE FROM scenario_version WHERE scenario_id=:sid"), {"sid": scenario_id})
                await session.execute(text("DELETE FROM scenario WHERE id=:sid"), {"sid": scenario_id})
            else:
                await session.execute(
                    text("UPDATE scenario SET status='archived', updated_at=now() WHERE id=:sid"),
                    {"sid": scenario_id},
                )
            await audit(session, principal, "scenario.delete", "scenario", scenario_id, {"hard": hard})
            await session.commit()
        return {"scenario_id": scenario_id, "archived": True, "hard": hard}

    # ------------------------------------------------------------ internals
    async def _insert_pending(
        self,
        scenario_id: str,
        document: dict[str, Any],
        checksum: str,
        uri: str,
        *,
        expected: int,
        principal: Principal,
    ) -> None:
        version = int(document["version"])
        async with self.db.session() as session:
            if expected == 0:
                await self._insert_scenario_row(session, scenario_id, document, principal)
            await self._insert_version_intent(
                session, scenario_id, version, uri, checksum, expected, document, principal
            )
            await self._write_projection(session, scenario_id, document)
            await audit(session, principal, "scenario.publish_pending", "scenario", scenario_id, {"version": version})
            await session.commit()

    async def _insert_scenario_row(
        self,
        session: AsyncSession,
        scenario_id: str,
        document: dict[str, Any],
        principal: Principal,
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO scenario(id,name,description,current_version,source_type,log_id,log_uri,
                  log_checksum,file_uri,file_checksum,start_ts,end_ts,trigger_ts,extra,owner,project,status)
                VALUES (:id,:name,:desc,0,:stype,:log_id,:log_uri,:log_sha,'','',:start,:end,:trig,
                  CAST(:extra AS JSONB),:owner,:project,'active')
                """
            ),
            {
                "id": scenario_id,
                "name": document["name"],
                "desc": document["description"],
                "stype": document["source"]["type"],
                "log_id": document["source"].get("log_id", ""),
                "log_uri": document["source"].get("log_uri", ""),
                "log_sha": document["source"].get("log_checksum", ""),
                "start": document["time_window"]["start_ts"],
                "end": document["time_window"]["end_ts"],
                "trig": document["time_window"]["trigger_ts"],
                "extra": dumps(document["extra"]),
                "owner": principal.user,
                "project": document["project"],
            },
        )

    async def _insert_version_intent(
        self,
        session: AsyncSession,
        scenario_id: str,
        version: int,
        uri: str,
        checksum: str,
        expected: int,
        document: dict[str, Any],
        principal: Principal,
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO scenario_version(scenario_id,version,file_uri,file_checksum,publish_state,
                  expected_version,change_note,created_by)
                VALUES (:sid,:ver,:uri,:sha,'pending',:expected,:note,:by)
                """
            ),
            {
                "sid": scenario_id,
                "ver": version,
                "uri": uri,
                "sha": checksum,
                "expected": expected,
                "note": document["description"][:200],
                "by": principal.user,
            },
        )

    async def _finish_publish(
        self, scenario_id: str, version: int, checksum: str, principal: Principal, *, expected: int
    ) -> None:
        async with self.db.session() as session:
            await session.execute(
                text(
                    """
                    UPDATE scenario_version SET publish_state='published', file_checksum=:sha
                    WHERE scenario_id=:sid AND version=:ver
                    """
                ),
                {"sid": scenario_id, "ver": version, "sha": checksum},
            )
            result = await session.execute(
                text(
                    """
                    UPDATE scenario SET current_version=:ver, file_uri=:uri, file_checksum=:sha, updated_at=now()
                    WHERE id=:sid AND current_version=:expected
                    """
                ),
                {
                    "sid": scenario_id,
                    "ver": version,
                    "uri": scenario_uri(scenario_id, version),
                    "sha": checksum,
                    "expected": expected,
                },
            )
            if not affected(result):
                await session.rollback()
                raise conflict("VERSION_CONFLICT", "场景当前版本已变化，请刷新后重试")
            await audit(session, principal, "scenario.publish", "scenario", scenario_id, {"version": version})
            await session.commit()


def _encode_time_cursor(created_at: Any, ident: str) -> str:
    from backend.shared.canonical import encode_cursor

    timestamp = created_at.timestamp() if isinstance(created_at, datetime) else float(created_at)
    return encode_cursor(f"{timestamp:.6f}", ident)


def _cursor_parts(cursor: str) -> list[str]:
    from backend.shared.canonical import decode_cursor

    return decode_cursor(cursor, 2)


def _suffix() -> str:
    import secrets

    return secrets.token_hex(3)


def _now_local() -> datetime:
    return datetime.now(UTC)
