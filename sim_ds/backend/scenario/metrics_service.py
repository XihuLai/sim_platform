"""Metric five-layer CRUD and cache-friendly lookups."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator, SchemaError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.models import (
    MetricConfig,
    MetricDef,
    MetricTemplate,
    MetricType,
    ScenarioMetricInstance,
)
from backend.scenario.common import loads
from backend.scenario.metrics import validate_def_templates, validate_instance
from backend.shared.auth import Principal, audit
from backend.shared.db import Database, affected, dumps
from backend.shared.errors import AppError, conflict, not_found

FIXED_CATEGORIES = ("comfort", "compliance", "safety", "efficiency", "navigation")


class MetricService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def categories(self) -> list[dict[str, Any]]:
        return await self.db.fetch_all("SELECT * FROM metric_category ORDER BY sort_order, id")

    async def update_category(self, category_id: str, body: dict[str, Any], principal: Principal) -> dict[str, Any]:
        if category_id not in FIXED_CATEGORIES:
            raise AppError("FIXED_CATEGORY", "分类集合固定，不能新增或删除", status=409)
        allowed: dict[str, Any] = {key: body[key] for key in ("name", "sort_order", "description") if key in body}
        if not allowed:
            raise AppError("NO_FIELDS", "没有可更新字段", status=422)
        assignments = ", ".join(f"{key}=:{key}" for key in allowed)
        async with self.db.session() as session:
            await session.execute(
                text(f"UPDATE metric_category SET {assignments} WHERE id=:id"),
                {**allowed, "id": category_id},
            )
            await audit(session, principal, "metric.category.update", "metric_category", category_id, allowed)
            await session.commit()
        row = await self.db.fetch_one("SELECT * FROM metric_category WHERE id=:id", {"id": category_id})
        if row is None:
            raise not_found("Metric 分类", category_id)
        return row

    async def types(self, category_id: str | None = None) -> list[dict[str, Any]]:
        if category_id:
            return await self.db.fetch_all(
                "SELECT * FROM metric_type WHERE category_id=:cid ORDER BY sort_order, id",
                {"cid": category_id},
            )
        return await self.db.fetch_all("SELECT * FROM metric_type ORDER BY category_id, sort_order, id")

    async def create_type(self, body: MetricType, principal: Principal) -> dict[str, Any]:
        async with self.db.session() as session:
            exists = await session.execute(
                text("SELECT 1 FROM metric_category WHERE id=:id"), {"id": body.category_id}
            )
            if exists.first() is None:
                raise AppError("CATEGORY_NOT_FOUND", f"分类 {body.category_id} 不存在", status=422)
            if body.parent_id:
                parent = await session.execute(
                    text("SELECT category_id FROM metric_type WHERE id=:id"), {"id": body.parent_id}
                )
                row = parent.first()
                if row is None or row[0] != body.category_id:
                    raise AppError("PARENT_INVALID", "父类型不存在或跨分类", status=422)
            try:
                await session.execute(
                    text(
                        "INSERT INTO metric_type(id,category_id,parent_id,name,sort_order,description,status) "
                        "VALUES (:id,:cid,:parent,:name,:order,:desc,:status)"
                    ),
                    {
                        "id": body.id,
                        "cid": body.category_id,
                        "parent": body.parent_id,
                        "name": body.name,
                        "order": body.sort_order,
                        "desc": body.description,
                        "status": body.status,
                    },
                )
            except Exception as exc:
                raise conflict("TYPE_EXISTS", f"类型 {body.id} 已存在") from exc
            await audit(session, principal, "metric.type.create", "metric_type", body.id)
            await session.commit()
        return body.model_dump()

    async def update_type(self, type_id: str, body: dict[str, Any], principal: Principal) -> dict[str, Any]:
        allowed: dict[str, Any] = {
            key: body[key]
            for key in ("name", "sort_order", "description", "status", "parent_id")
            if key in body
        }
        if not allowed:
            raise AppError("NO_FIELDS", "没有可更新字段", status=422)
        assignments = ", ".join(f"{key}=:{key}" for key in allowed)
        async with self.db.session() as session:
            result = await session.execute(
                text(f"UPDATE metric_type SET {assignments} WHERE id=:id"),
                {**allowed, "id": type_id},
            )
            if affected(result) == 0:
                raise not_found("Metric 类型", type_id)
            await audit(session, principal, "metric.type.update", "metric_type", type_id, allowed)
            await session.commit()
        row = await self.db.fetch_one("SELECT * FROM metric_type WHERE id=:id", {"id": type_id})
        assert row is not None
        return row

    async def delete_type(self, type_id: str, principal: Principal) -> dict[str, Any]:
        return await self.update_type(type_id, {"status": "deprecated"}, principal)

    async def templates(self, kind: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM metric_template"
        params: dict[str, Any] = {}
        if kind:
            sql += " WHERE kind=:kind"
            params["kind"] = kind
        rows = await self.db.fetch_all(sql + " ORDER BY kind, id", params)
        for row in rows:
            row["env_schema"] = loads(row["env_schema"])
            row["env_example"] = loads(row["env_example"])
        return rows

    async def create_template(self, body: MetricTemplate, principal: Principal) -> dict[str, Any]:
        _check_schema(body.env_schema)
        async with self.db.session() as session:
            try:
                await session.execute(
                    text(
                        "INSERT INTO metric_template(id,name,kind,env_schema,env_example,status,description) "
                        "VALUES (:id,:name,:kind,CAST(:schema AS JSONB),CAST(:example AS JSONB),:status,:desc)"
                    ),
                    {
                        "id": body.id,
                        "name": body.name,
                        "kind": body.kind,
                        "schema": dumps(body.env_schema),
                        "example": dumps(body.env_example),
                        "status": body.status,
                        "desc": body.description,
                    },
                )
            except Exception as exc:
                raise conflict("TEMPLATE_EXISTS", f"模板 {body.id} 已存在") from exc
            await audit(session, principal, "metric.template.create", "metric_template", body.id)
            await session.commit()
        return {**body.model_dump(), "env_schema": body.env_schema, "env_example": body.env_example}

    async def update_template(self, template_id: str, body: dict[str, Any], principal: Principal) -> dict[str, Any]:
        allowed: dict[str, Any] = {key: body[key] for key in ("name", "kind", "status", "description") if key in body}
        if "env_schema" in body:
            _check_schema(body["env_schema"])
            allowed["env_schema"] = dumps(body["env_schema"])
        if "env_example" in body:
            allowed["env_example"] = dumps(body["env_example"])
        if not allowed:
            raise AppError("NO_FIELDS", "没有可更新字段", status=422)
        assignments = ", ".join(
            f"{key}=CAST(:{key} AS JSONB)" if key.startswith("env_") else f"{key}=:{key}"
            for key in allowed
        )
        async with self.db.session() as session:
            result = await session.execute(
                text(f"UPDATE metric_template SET {assignments} WHERE id=:id"),
                {**allowed, "id": template_id},
            )
            if affected(result) == 0:
                raise not_found("Metric 模板", template_id)
            await audit(session, principal, "metric.template.update", "metric_template", template_id)
            await session.commit()
        row = await self.db.fetch_one("SELECT * FROM metric_template WHERE id=:id", {"id": template_id})
        assert row is not None
        row["env_schema"] = loads(row["env_schema"])
        row["env_example"] = loads(row["env_example"])
        return row

    async def delete_template(self, template_id: str, principal: Principal) -> dict[str, Any]:
        return await self.update_template(template_id, {"status": "deprecated"}, principal)

    async def defs(self, type_id: str | None = None, status: str = "active") -> list[dict[str, Any]]:
        clauses = ["d.status=:status"]
        params: dict[str, Any] = {"status": status}
        if type_id:
            clauses.append("d.type_id=:type_id")
            params["type_id"] = type_id
        rows = await self.db.fetch_all(
            f"""
            SELECT d.*, c.id AS category_id
            FROM metric_def d
            JOIN metric_type t ON t.id=d.type_id
            JOIN metric_category c ON c.id=t.category_id
            WHERE {' AND '.join(clauses)}
            ORDER BY c.sort_order, t.id, d.id, d.version DESC
            """,
            params,
        )
        for row in rows:
            for key in ("trigger_templates", "trigger_functions", "trigger_ops", "function_templates", "functions", "ops"):
                row[key] = loads(row[key])
        return rows

    async def create_def(self, body: MetricDef, principal: Principal) -> dict[str, Any]:
        async with self.db.session() as session:
            await validate_def_templates(session, body)
            await self._validate_rule_config(session, body)
            exists = await session.execute(
                text("SELECT 1 FROM metric_def WHERE id=:id"), {"id": body.id}
            )
            if exists.first() is not None:
                raise conflict("DEF_EXISTS", f"Metric 定义 {body.id} 已存在，请使用新版本接口")
            await self._insert_def(session, body)
            await audit(session, principal, "metric.def.create", "metric_def", body.id, {"version": body.version})
            await session.commit()
        return await self.get_def(body.id, body.version)

    async def update_def(self, def_id: str, body: MetricDef, principal: Principal) -> dict[str, Any]:
        async with self.db.session() as session:
            await validate_def_templates(session, body)
            await self._validate_rule_config(session, body)
            row = (
                await session.execute(
                    text("SELECT MAX(version) AS version FROM metric_def WHERE id=:id"), {"id": def_id}
                )
            ).first()
            if row is None or row[0] is None:
                raise not_found("Metric 定义", def_id)
            if body.version not in (row[0], 0):
                raise conflict("VERSION_CONFLICT", "请基于最新版本提交", current=row[0], expected=body.version)
            next_version = int(row[0]) + 1
            next_body = body.model_copy(update={"id": def_id, "version": next_version})
            await self._insert_def(session, next_body)
            await audit(session, principal, "metric.def.update", "metric_def", def_id, {"version": next_version})
            await session.commit()
        return await self.get_def(def_id, next_version)

    async def get_def(self, def_id: str, version: int) -> dict[str, Any]:
        row = await self.db.fetch_one(
            "SELECT * FROM metric_def WHERE id=:id AND version=:ver", {"id": def_id, "ver": version}
        )
        if row is None:
            raise not_found("Metric 定义", f"{def_id}@{version}")
        for key in ("trigger_templates", "trigger_functions", "trigger_ops", "function_templates", "functions", "ops"):
            row[key] = loads(row[key])
        return row

    async def delete_def(self, def_id: str, principal: Principal) -> dict[str, Any]:
        async with self.db.session() as session:
            result = await session.execute(
                text("UPDATE metric_def SET status='deprecated' WHERE id=:id"), {"id": def_id}
            )
            if affected(result) == 0:
                raise not_found("Metric 定义", def_id)
            await audit(session, principal, "metric.def.deprecate", "metric_def", def_id)
            await session.commit()
        return {"id": def_id, "status": "deprecated"}

    async def _validate_rule_config(self, session: AsyncSession, body: MetricDef) -> None:
        if not body.trigger_functions and not body.functions:
            return
        config = MetricConfig(
            trigger_functions=body.trigger_functions,
            trigger_ops=body.trigger_ops,
            functions=body.functions,
            ops=body.ops,
            ret=body.ret,
            action=body.action,
            level=body.level,
            is_global=body.is_global,
        )
        instance = ScenarioMetricInstance(
            metric_def_id=body.id,
            metric_def_ver=body.version,
            config=config,
        )
        await validate_instance(session, instance)

    async def _insert_def(self, session: AsyncSession, body: MetricDef) -> None:
        await session.execute(
            text(
                """
                INSERT INTO metric_def(id,version,type_id,name,level,business_type,run_mode,is_global,
                  trigger_templates,trigger_functions,trigger_ops,function_templates,functions,ops,
                  ret,action,status,description)
                VALUES (:id,:ver,:type_id,:name,:level,:btype,:run_mode,:global,
                  CAST(:tt AS JSONB),CAST(:tf AS JSONB),CAST(:tops AS JSONB),CAST(:ft AS JSONB),
                  CAST(:funcs AS JSONB),CAST(:ops AS JSONB),:ret,:action,:status,:desc)
                """
            ),
            {
                "id": body.id,
                "ver": body.version,
                "type_id": body.type_id,
                "name": body.name,
                "level": body.level,
                "btype": body.business_type,
                "run_mode": body.run_mode,
                "global": body.is_global,
                "tt": dumps([ref.model_dump() for ref in body.trigger_templates]),
                "tf": dumps([item.model_dump() for item in body.trigger_functions]),
                "tops": dumps(body.trigger_ops),
                "ft": dumps([ref.model_dump() for ref in body.function_templates]),
                "funcs": dumps([item.model_dump() for item in body.functions]),
                "ops": dumps(body.ops),
                "ret": body.ret,
                "action": body.action,
                "status": body.status,
                "desc": body.description,
            },
        )

def _check_schema(schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise AppError(
            "INVALID_ENV_SCHEMA",
            "env_schema 不是合法的 JSON Schema",
            status=422,
            detail={"reason": exc.message},
        ) from exc
