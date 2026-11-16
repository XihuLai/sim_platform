"""Authentication and project scoping.

Development/CI may disable authentication explicitly. Production startup fails
unless authentication, a token registry and project scoping are configured.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.shared.config import Settings, TokenPrincipal
from backend.shared.db import Database, dumps
from backend.shared.errors import AppError


@dataclass(frozen=True)
class Principal:
    user: str
    project: str
    projects: tuple[str, ...]
    admin: bool = False
    authenticated: bool = True
    role: str = "user"
    max_priority: int = 9
    max_running_cases: int | None = None
    max_cpu: int | None = None
    max_mem_gb: int | None = None
    max_gpu: int | None = None


def _token_principal(settings: Settings, token: str) -> TokenPrincipal | None:
    return settings.tokens.get(token)


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def resolve_principal(request: Request, settings: Settings, db: Database) -> Principal:
    token = _extract_token(request)
    if token:
        found = _token_principal(settings, token)
        if found is not None:
            return _static_principal(request, found)
        row = await db.fetch_one(
            """
            SELECT u.* FROM sim_session s JOIN sim_user u ON u.id=s.user_id
            WHERE s.token=:token AND s.expires_at > now() AND u.status='active'
            """,
            {"token": token},
        )
        if row is None:
            raise AppError("UNAUTHENTICATED", "访问令牌无效或已过期", status=401)
        return _account_principal(request, row)

    if settings.auth_mode == "dev":
        user = request.headers.get("x-user", "dev")
        project = request.headers.get("x-project", "default")
        return Principal(
            user=user,
            project=project,
            projects=(project,),
            admin=True,
            role="super_admin",
            max_priority=9,
        )
    raise AppError("UNAUTHENTICATED", "缺少访问令牌", status=401)


def _requested_project(request: Request, projects: tuple[str, ...], admin: bool) -> str:
    requested = request.headers.get("x-project") or (projects[0] if projects else "")
    if not requested:
        raise AppError("PROJECT_REQUIRED", "需要 X-Project 指定项目", status=400)
    if not admin and requested not in projects:
        raise AppError("FORBIDDEN", "无权访问该项目", status=403, detail={"project": requested})
    return requested


def _static_principal(request: Request, found: TokenPrincipal) -> Principal:
    project = _requested_project(request, found.projects, found.admin)
    return Principal(
        user=found.user,
        project=project,
        projects=found.projects,
        admin=found.admin,
        role="super_admin" if found.admin else "user",
        max_priority=9,
    )


def _account_principal(request: Request, row: dict[str, object]) -> Principal:
    role = str(row["role"])
    admin = role in {"admin", "super_admin"}
    project = _requested_project(request, (str(row["project"]),), admin)
    return Principal(
        user=str(row["username"]),
        project=project,
        projects=(str(row["project"]),),
        admin=admin,
        role=role,
        max_priority=int(str(row["max_priority"])),
        max_running_cases=row.get("max_running_cases"),  # type: ignore[arg-type]
        max_cpu=row.get("max_cpu"),  # type: ignore[arg-type]
        max_mem_gb=row.get("max_mem_gb"),  # type: ignore[arg-type]
        max_gpu=row.get("max_gpu"),  # type: ignore[arg-type]
    )


def require_same_project(principal: Principal, project: str | None) -> None:
    if project and project != principal.project and not principal.admin:
        raise AppError(
            "FORBIDDEN",
            "跨项目访问被拒绝",
            status=403,
            detail={"project": principal.project, "resource_project": project},
        )


async def audit(
    session: AsyncSession,
    principal: Principal,
    action: str,
    resource_type: str,
    resource_id: str,
    detail: dict[str, object] | None = None,
) -> None:
    await session.execute(
        text(_AUDIT_SQL),
        {
            "actor": principal.user,
            "project": principal.project,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "detail": dumps(detail or {}),
        },
    )


_AUDIT_SQL = """
INSERT INTO audit_log(actor, project, action, resource_type, resource_id, detail)
VALUES (:actor, :project, :action, :resource_type, :resource_id, CAST(:detail AS JSONB))
"""
