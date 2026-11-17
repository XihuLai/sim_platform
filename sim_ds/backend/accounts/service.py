"""Account CRUD, password login and session issuing."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.accounts.models import UserCreate, UserUpdate
from backend.shared.auth import Principal, audit
from backend.shared.canonical import iso, utcnow
from backend.shared.config import Settings
from backend.shared.db import Database
from backend.shared.errors import AppError, conflict, not_found
from backend.shared.passwords import hash_password, verify_password

SESSION_HOURS = 24


class AccountService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def login(self, username: str, password: str) -> dict[str, Any]:
        row = await self.db.fetch_one(
            "SELECT * FROM sim_user WHERE username=:username AND status='active'",
            {"username": username},
        )
        if row is None or not verify_password(password, row["password_hash"]):
            raise AppError("INVALID_CREDENTIALS", "用户名或密码错误", status=401)
        token = secrets.token_urlsafe(32)
        expires = utcnow() + timedelta(hours=SESSION_HOURS)
        await self.db.execute(
            "INSERT INTO sim_session(token,user_id,expires_at) VALUES (:token,:uid,:expires)",
            {"token": token, "uid": row["id"], "expires": expires},
        )
        return {"token": token, "expires_at": iso(expires), "user": self.view(row)}

    async def logout(self, token: str) -> None:
        await self.db.execute("DELETE FROM sim_session WHERE token=:token", {"token": token})

    async def list_users(self) -> list[dict[str, Any]]:
        rows = await self.db.fetch_all(
            "SELECT * FROM sim_user ORDER BY CASE role WHEN 'super_admin' THEN 0 "
            "WHEN 'admin' THEN 1 ELSE 2 END, username"
        )
        return [self.view(row) for row in rows]

    async def create_user(self, body: UserCreate, principal: Principal) -> dict[str, Any]:
        self._check_role_change(principal, body.role)
        user_id = "usr_" + secrets.token_hex(8)
        async with self.db.session() as session:
            try:
                await session.execute(
                    text(
                        """
                        INSERT INTO sim_user(id,username,password_hash,display_name,role,project,
                          max_priority,max_daily_cases,max_running_cases,max_cpu,max_mem_gb,max_gpu)
                        VALUES (:id,:username,:hash,:display,:role,:project,:priority,:daily,:cases,:cpu,:mem,:gpu)
                        """
                    ),
                    {
                        "id": user_id,
                        "username": body.username,
                        "hash": hash_password(body.password),
                        "display": body.display_name,
                        "role": body.role,
                        "project": body.project,
                        "priority": body.max_priority,
                        "daily": body.max_daily_cases,
                        "cases": body.max_running_cases,
                        "cpu": body.max_cpu,
                        "mem": body.max_mem_gb,
                        "gpu": body.max_gpu,
                    },
                )
            except IntegrityError as exc:
                raise conflict("USERNAME_EXISTS", f"用户名 {body.username} 已存在") from exc
            await audit(
                session,
                principal,
                "user.create",
                "sim_user",
                user_id,
                {"username": body.username, "role": body.role},
            )
            await session.commit()
        row = await self.db.fetch_one("SELECT * FROM sim_user WHERE id=:id", {"id": user_id})
        if row is None:
            raise not_found("账号", user_id)
        return self.view(row)

    async def update_user(
        self, user_id: str, body: UserUpdate, principal: Principal
    ) -> dict[str, Any]:
        row = await self.db.fetch_one("SELECT * FROM sim_user WHERE id=:id", {"id": user_id})
        if row is None:
            raise not_found("账号", user_id)
        if row["role"] == "super_admin" and principal.role != "super_admin":
            raise AppError("FORBIDDEN", "只有超级管理员可以修改超级管理员", status=403)
        if body.role is not None:
            self._check_role_change(principal, body.role)
        values = body.model_dump(exclude_unset=True)
        if "password" in values:
            values["password_hash"] = hash_password(values.pop("password"))
        if not values:
            return self.view(row)
        assignments = ", ".join(
            f"{key}=CAST(:{key} AS JSONB)" if False else f"{key}=:{key}" for key in values
        )
        async with self.db.session() as session:
            await session.execute(
                text(f"UPDATE sim_user SET {assignments}, updated_at=now() WHERE id=:id"),
                {**values, "id": user_id},
            )
            await audit(
                session,
                principal,
                "user.update",
                "sim_user",
                user_id,
                {key: value for key, value in values.items() if key != "password_hash"},
            )
            await session.commit()
        updated = await self.db.fetch_one("SELECT * FROM sim_user WHERE id=:id", {"id": user_id})
        if updated is None:
            raise not_found("账号", user_id)
        return self.view(updated)

    @staticmethod
    def _check_role_change(principal: Principal, role: str) -> None:
        if role in {"admin", "super_admin"} and principal.role != "super_admin":
            raise AppError("FORBIDDEN", "只有超级管理员可以授予管理员权限", status=403)

    @staticmethod
    def view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row.get("display_name") or row["username"],
            "role": row["role"],
            "admin": row["role"] in {"admin", "super_admin"},
            "status": row["status"],
            "project": row["project"],
            "max_priority": row["max_priority"],
            "max_daily_cases": row.get("max_daily_cases"),
            "max_running_cases": row.get("max_running_cases"),
            "max_cpu": row.get("max_cpu"),
            "max_mem_gb": row.get("max_mem_gb"),
            "max_gpu": row.get("max_gpu"),
            "created_at": iso(row.get("created_at")),
            "updated_at": iso(row.get("updated_at")),
        }
