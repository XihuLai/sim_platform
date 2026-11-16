"""PostgreSQL-backed test fixtures. Tests skip cleanly when PostgreSQL is absent."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
from backend.shared.auth import Principal
from backend.shared.db import Database

DEMO_TABLES = (
    "archive_export",
    "audit_log",
    "case_result",
    "case_run",
    "data_source",
    "metric_def",
    "metric_type",
    "outbox",
    "project_quota",
    "resource_reservation",
    "sim_session",
    "scenario",
    "scenario_metric",
    "scenario_set",
    "scenario_set_member",
    "scenario_set_version",
    "scenario_tag",
    "scenario_version",
    "sim_task",
    "tag",
    "task_control_request",
    "task_expand_cursor",
    "task_metric_agg",
    "task_summary",
    "worker",
)


def _parts() -> tuple[str, str, str, str, str]:
    return (
        os.getenv("SIM_PG_HOST", "127.0.0.1"),
        os.getenv("SIM_PG_PORT", "5432"),
        os.getenv("SIM_PG_USER", "postgres"),
        os.getenv("SIM_PG_PASSWORD", "xh127"),
        os.getenv("SIM_PG_TEST_DATABASE", "sim_test"),
    )


def _sync_url(database: str | None = None) -> str:
    host, port, user, password, name = _parts()
    explicit = os.getenv("SIM_TEST_DATABASE_URL")
    if explicit and database is None:
        return explicit.replace("postgresql+asyncpg://", "postgresql://")
    return f"postgresql://{user}:{password}@{host}:{port}/{database or name}"


@pytest.fixture(scope="session")
def postgres_url() -> str:
    try:
        with psycopg.connect(_sync_url("postgres"), autocommit=True) as conn:
            name = _parts()[4]
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (name,)
            ).fetchone()
            if not exists:
                conn.execute(f'CREATE DATABASE "{name}"')
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    from scripts import migrate

    with psycopg.connect(_sync_url(), autocommit=True) as conn:
        migrate.reset(conn)
        migrate.ledger(conn)
        for path in sorted(migrate.MIGRATIONS.glob("*.sql")):
            migrate.apply(conn, path)
    host, port, user, password, name = _parts()
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


@pytest.fixture
def clean(postgres_url: str) -> Iterator[None]:
    tables = ", ".join(DEMO_TABLES)
    with psycopg.connect(_sync_url(), autocommit=True) as conn:
        conn.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
        conn.execute("DELETE FROM sim_user WHERE username <> 'df_sim'")
        conn.execute(
            "INSERT INTO project_quota(project,max_running_cases,max_cpu,max_mem_gb,max_gpu) "
            "VALUES ('default',64,64,256,4) ON CONFLICT DO NOTHING"
        )
    yield


@pytest.fixture
async def db(postgres_url: str, clean: None) -> AsyncIterator[Database]:
    database = Database(postgres_url)
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def principal() -> Principal:
    return Principal(
        user="tester", project="default", projects=("default", "other"), admin=False
    )
