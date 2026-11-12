"""Typed application errors mapped to the contract's {code,message,detail} shape."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}


def not_found(kind: str, ident: str) -> AppError:
    return AppError("NOT_FOUND", f"{kind} {ident} 不存在或无权访问", status=404)


def conflict(code: str, message: str, **detail: Any) -> AppError:
    return AppError(code, message, status=409, detail=detail)
