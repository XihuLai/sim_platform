#!/usr/bin/env python3
"""Apply PostgreSQL migrations in order, with an applied-version ledger."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"


def dsn() -> str:
    explicit = os.getenv("SIM_DATABASE_URL", "")
    if explicit:
        return explicit.replace("postgresql+asyncpg://", "postgresql://").replace(
            "postgresql+psycopg://", "postgresql://"
        )
    user = os.getenv("SIM_PG_USER", "postgres")
    password = os.getenv("SIM_PG_PASSWORD", "xh127")
    host = os.getenv("SIM_PG_HOST", "127.0.0.1")
    port = os.getenv("SIM_PG_PORT", "5432")
    database = os.getenv("SIM_PG_DATABASE", "sim_dev")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def ledger(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migration (
          version TEXT PRIMARY KEY,
          filename TEXT NOT NULL,
          checksum TEXT NOT NULL,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def apply(conn: psycopg.Connection[tuple[object, ...]], path: Path) -> bool:
    version = path.name.split("_", 1)[0]
    exists = conn.execute("SELECT 1 FROM schema_migration WHERE version=%s", (version,)).fetchone()
    if exists:
        return False
    body = path.read_text(encoding="utf-8")
    checksum = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
    try:
        conn.execute(body)
        conn.execute(
            "INSERT INTO schema_migration(version, filename, checksum) VALUES (%s,%s,%s)",
            (version, path.name, checksum),
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return True


def reset(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    conn.execute("DROP SCHEMA public CASCADE")
    conn.execute("CREATE SCHEMA public")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="drop the public schema first")
    parser.add_argument("--database-url", default=dsn())
    args = parser.parse_args()
    with psycopg.connect(args.database_url, autocommit=True) as conn:
        if args.reset:
            reset(conn)
            print("schema reset")
        ledger(conn)
        applied = 0
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if apply(conn, path):
                print(f"applied {path.name}")
                applied += 1
        print(f"done: {applied} migration(s) applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
