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
from backend.shared.db import dumps
from backend.shared.errors import AppError


@dataclass(frozen=True)
class Principal:
    user: str
    project: str
    projects: tuple[str, ...]
    admin: bool = False
    authenticated: bool = True


def _token_principal(settings: Settings, token: str) -> TokenPrincipal | None:
    return settings.tokens.get(token)


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def resolve_principal(request: Request, settings: Settings) -> Principal:
    if settings.auth_mode == "dev":
        user = request.headers.get("x-user", "dev")
        project = request.headers.get("x-project", "default")
        return Principal(user=user, project=project, projects=(project,), admin=True)

    token = _extract_token(request)
    if not token:
        raise AppError("UNAUTHENTICATED", "缺少访问令牌", status=401)
    found = _token_principal(settings, token)
    if found is None:
        raise AppError("UNAUTHENTICATED", "访问令牌无效", status=401)
    requested = request.headers.get("x-project") or (found.projects[0] if found.projects else "")
    if not requested:
        raise AppError("PROJECT_REQUIRED", "需要 X-Project 指定项目", status=400)
    if not found.admin and requested not in found.projects:
        raise AppError("FORBIDDEN", "无权访问该项目", status=403, detail={"project": requested})
    return Principal(
        user=found.user,
        project=requested,
        projects=found.projects,
        admin=found.admin,
        authenticated=True,
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
