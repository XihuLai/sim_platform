"""Async database access. Raw SQL is used so PostgreSQL features (SKIP LOCKED,
JSONB, partial indexes, advisory locks) stay explicit and reviewable."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
        )
        self.dialect = self.engine.dialect.name
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    @property
    def is_postgres(self) -> bool:
        return self.dialect == "postgresql"

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        await self.engine.dispose()

    def text_array(self, values: Sequence[str]) -> list[str] | str:
        """Array bind value: asyncpg wants a list, SQLite wants a text literal."""
        return list(values) if self.is_postgres else array_literal(values)

    async def fetch_one(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        async with self.session() as session:
            row = (await session.execute(text(sql), params or {})).mappings().first()
            return dict(row) if row else None

    async def fetch_all(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        async with self.session() as session:
            rows = (await session.execute(text(sql), params or {})).mappings().all()
            return [dict(row) for row in rows]

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        async with self.session() as session:
            result = await session.execute(text(sql), params or {})
            await session.commit()
            return affected(result)

    async def executemany(self, sql: str, rows: Sequence[dict[str, Any]]) -> None:
        async with self.session() as session:
            await session.execute(text(sql), list(rows))
            await session.commit()


def affected(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


def dumps(value: Any) -> str:
    """JSON text for a JSONB cast parameter."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def jsonb(value: Any) -> str:
    return dumps(value)


def array_literal(values: Sequence[str]) -> str:
    """PostgreSQL text[] literal, safe for parameter casting."""
    escaped = []
    for value in values:
        escaped.append('"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"')
    return "{" + ",".join(escaped) + "}"
