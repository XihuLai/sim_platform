"""Process configuration loaded from the environment.

The platform runs against PostgreSQL by default. SQLite is accepted only for
explicit local development; the scheduler refuses to start on it (contract 3.3).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TokenPrincipal:
    user: str
    projects: tuple[str, ...]
    admin: bool = False


def _data_dir() -> Path:
    return Path(os.getenv("SIM_DATA_DIR", str(ROOT / "data"))).resolve()


def _default_database_url() -> str:
    explicit = os.getenv("SIM_DATABASE_URL")
    if explicit:
        return explicit
    host = os.getenv("SIM_PG_HOST", "127.0.0.1")
    port = os.getenv("SIM_PG_PORT", "5432")
    user = os.getenv("SIM_PG_USER", "postgres")
    password = os.getenv("SIM_PG_PASSWORD", "xh127")
    database = os.getenv("SIM_PG_DATABASE", "sim_dev")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def _tokens(raw: str) -> dict[str, TokenPrincipal]:
    if not raw:
        return {}
    parsed: dict[str, Any] = json.loads(raw)
    result: dict[str, TokenPrincipal] = {}
    for token, value in parsed.items():
        if isinstance(value, str):
            result[token] = TokenPrincipal(user=value, projects=("default",))
        else:
            result[token] = TokenPrincipal(
                user=str(value["user"]),
                projects=tuple(value.get("projects", ["default"])),
                admin=bool(value.get("admin", False)),
            )
    return result


@dataclass(frozen=True)
class Settings:
    env: str = "dev"
    database_url: str = field(default_factory=_default_database_url)
    data_dir: Path = field(default_factory=_data_dir)
    auth_mode: str = "dev"
    tokens: dict[str, TokenPrincipal] = field(default_factory=dict)
    worker_id: str = "local-1"
    worker_cpu: int = 64
    worker_mem_gb: int = 256
    worker_gpu: int = 4
    scheduler_enabled: bool = True
    scheduler_tick_sec: float = 0.5
    scheduler_batch: int = 50
    aging_sec: int = 60
    heartbeat_timeout_sec: int = 30
    reconcile_sec: int = 30
    expand_batch: int = 1000
    sync_expand_limit: int = 500
    seed: int = 7
    api_prefix: str = "/api"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql", "postgres"))

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"prod", "production"}

    def validate(self) -> None:
        if self.is_production and self.auth_mode != "required":
            raise SystemExit(
                "production requires SIM_AUTH_MODE=required; refusing to start without authentication"
            )
        if self.is_production and not self.tokens:
            raise SystemExit("production requires SIM_API_TOKENS with at least one principal")
        self.data_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    env = os.getenv("SIM_ENV", "dev")
    auth_mode = os.getenv("SIM_AUTH_MODE", "required" if env.lower() in {"prod", "production"} else "dev")
    settings = Settings(
        env=env,
        database_url=_default_database_url(),
        data_dir=_data_dir(),
        auth_mode=auth_mode,
        tokens=_tokens(os.getenv("SIM_API_TOKENS", "")),
        worker_id=os.getenv("SIM_WORKER_ID", "local-1"),
        worker_cpu=int(os.getenv("SIM_WORKER_CPU", "64")),
        worker_mem_gb=int(os.getenv("SIM_WORKER_MEM_GB", "256")),
        worker_gpu=int(os.getenv("SIM_WORKER_GPU", "4")),
        scheduler_enabled=os.getenv("SIM_SCHEDULER_ENABLED", "1") not in {"0", "false", "no"},
        scheduler_tick_sec=float(os.getenv("SIM_SCHEDULER_TICK_SEC", "0.5")),
        scheduler_batch=int(os.getenv("SIM_SCHEDULER_BATCH", "50")),
        aging_sec=int(os.getenv("SIM_AGING_SEC", "60")),
        heartbeat_timeout_sec=int(os.getenv("SIM_HEARTBEAT_TIMEOUT_SEC", "30")),
        reconcile_sec=int(os.getenv("SIM_RECONCILE_SEC", "30")),
        expand_batch=int(os.getenv("SIM_EXPAND_BATCH", "1000")),
        sync_expand_limit=int(os.getenv("SIM_SYNC_EXPAND_LIMIT", "500")),
        seed=int(os.getenv("SIM_SEED", "7")),
    )
    settings.validate()
    return settings
