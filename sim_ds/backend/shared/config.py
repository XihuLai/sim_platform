"""Process configuration loaded from the environment.

The platform runs against PostgreSQL by default. SQLite is accepted only for
explicit local development; the scheduler refuses to start on it (contract 3.3).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_KEYS = {
    "SIM_ENV",
    "SIM_DATABASE_URL",
    "SIM_PG_HOST",
    "SIM_PG_PORT",
    "SIM_PG_USER",
    "SIM_PG_PASSWORD",
    "SIM_PG_DATABASE",
    "SIM_DATA_DIR",
    "SIM_AUTH_MODE",
    "SIM_API_TOKENS",
    "SIM_WORKER_ID",
    "SIM_EXECUTOR",
    "SIM_WORKER_CPU",
    "SIM_WORKER_MEM_GB",
    "SIM_WORKER_GPU",
    "SIM_SCHEDULER_ENABLED",
    "SIM_SCHEDULER_TICK_SEC",
    "SIM_SCHEDULER_BATCH",
    "SIM_AGING_SEC",
    "SIM_HEARTBEAT_TIMEOUT_SEC",
    "SIM_RECONCILE_SEC",
    "SIM_EXPAND_BATCH",
    "SIM_SYNC_EXPAND_LIMIT",
    "SIM_SEED",
    "SIM_ACCOUNT_AUTH",
    "SIM_SERVE_FRONTEND",
    "SIM_OBJECT_STORE_BUCKET",
    "SIM_OBJECT_STORE_ENDPOINT_URL",
    "SIM_OBJECT_STORE_REGION",
    "SIM_OBJECT_STORE_ACCESS_KEY",
    "SIM_OBJECT_STORE_SECRET_KEY",
    "SIM_OBJECT_STORE_PREFIX",
    "SIM_WORKER_API_URL",
    "SIM_WORKER_TOKEN",
    "SIM_WORKER_POLL_SEC",
    "SIM_WORKER_HEARTBEAT_SEC",
    "SIM_K8S_NAMESPACE",
    "SIM_K8S_WORKER_IMAGE",
    "SIM_K8S_WORKER_SECRET_NAME",
    "SIM_K8S_SERVICE_ACCOUNT",
    "SIM_K8S_IMAGE_PULL_SECRET",
    "SIM_K8S_POOL_NAME",
    "SIM_K8S_POOL_REPLICAS",
    "SIM_K8S_WORKER_SLOTS",
    "SIM_K8S_SLOT_CPU",
    "SIM_K8S_SLOT_MEM_GB",
    "SIM_K8S_SLOT_GPU",
    "KUBECONFIG",
}
YAML_SECRET_KEYS = {
    "SIM_DATABASE_URL",
    "SIM_PG_PASSWORD",
    "SIM_API_TOKENS",
    "SIM_OBJECT_STORE_ACCESS_KEY",
    "SIM_OBJECT_STORE_SECRET_KEY",
    "SIM_WORKER_TOKEN",
}


@dataclass(frozen=True)
class TokenPrincipal:
    user: str
    projects: tuple[str, ...]
    admin: bool = False


def _data_dir(source: Mapping[str, Any] | None = None) -> Path:
    values = source or os.environ
    return Path(str(values.get("SIM_DATA_DIR", ROOT / "data"))).resolve()


def _default_database_url(source: Mapping[str, Any] | None = None) -> str:
    values = source or os.environ
    explicit = values.get("SIM_DATABASE_URL")
    if explicit:
        return str(explicit)
    environment = str(values.get("SIM_ENV", "dev")).lower()
    default_database = (
        "sim_prod"
        if environment in {"prod", "production"}
        else "sim_test"
        if environment in {"test", "testing"}
        else "sim_dev"
    )
    host = values.get("SIM_PG_HOST", "127.0.0.1")
    port = values.get("SIM_PG_PORT", "5432")
    user = values.get("SIM_PG_USER", "postgres")
    password = values.get("SIM_PG_PASSWORD", "xh127")
    database = values.get("SIM_PG_DATABASE", default_database)
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def _tokens(raw: str | dict[str, Any]) -> dict[str, TokenPrincipal]:
    if not raw:
        return {}
    parsed: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else raw
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
    executor_backend: str = "local"
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
    account_auth: bool = True
    serve_frontend: bool = True
    object_store_bucket: str = ""
    object_store_endpoint_url: str | None = None
    object_store_region: str | None = None
    object_store_access_key: str | None = None
    object_store_secret_key: str | None = None
    object_store_prefix: str = ""
    worker_api_url: str = ""
    worker_token: str = ""
    worker_poll_sec: float = 2.0
    worker_heartbeat_sec: float = 10.0
    k8s_namespace: str = "default"
    k8s_worker_image: str = ""
    k8s_worker_secret_name: str = "sim-worker-secrets"
    k8s_service_account: str | None = None
    k8s_image_pull_secret: str | None = None
    k8s_pool_name: str = "sim-worker"
    k8s_pool_replicas: int = 2
    k8s_worker_slots: int = 1
    k8s_slot_cpu: int = 1
    k8s_slot_mem_gb: int = 1
    k8s_slot_gpu: int = 0
    kubeconfig: str | None = None

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
        if self.is_production and not self.tokens and not self.account_auth:
            raise SystemExit(
                "production requires SIM_API_TOKENS or database account authentication"
            )
        if self.executor_backend not in {"local", "k8s_pool"}:
            raise SystemExit("SIM_EXECUTOR must be local or k8s_pool")
        if self.executor_backend.startswith("k8s_"):
            missing = [
                name
                for name, value in (
                    ("SIM_K8S_WORKER_IMAGE", self.k8s_worker_image),
                    ("SIM_WORKER_API_URL", self.worker_api_url),
                    ("SIM_WORKER_TOKEN", self.worker_token),
                    ("SIM_OBJECT_STORE_BUCKET", self.object_store_bucket),
                )
                if not value
            ]
            if missing:
                raise SystemExit(
                    f"Kubernetes executor requires configuration: {', '.join(missing)}"
                )
            if self.k8s_pool_replicas < 1 or self.k8s_worker_slots < 1:
                raise SystemExit("Kubernetes worker replicas and slots must be positive")
            if self.k8s_slot_cpu < 1 or self.k8s_slot_mem_gb < 1 or self.k8s_slot_gpu < 0:
                raise SystemExit("Kubernetes slot CPU/memory must be positive and GPU non-negative")
        self.data_dir.mkdir(parents=True, exist_ok=True)


def _yaml_config(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as file:
            config = yaml.safe_load(file)
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"Cannot read SIM_CONFIG_FILE {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SystemExit(f"Invalid YAML in SIM_CONFIG_FILE {path}: {exc}") from exc
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise SystemExit(
            f"SIM_CONFIG_FILE {path} must contain a mapping of setting names to values"
        )
    if not all(isinstance(key, str) for key in config):
        raise SystemExit(f"All setting names in SIM_CONFIG_FILE {path} must be strings")
    unknown = sorted(set(config) - CONFIG_KEYS)
    if unknown:
        raise SystemExit(f"Unknown settings in SIM_CONFIG_FILE {path}: {', '.join(unknown)}")
    secrets = sorted(set(config) & YAML_SECRET_KEYS)
    if secrets:
        raise SystemExit(
            f"Secrets must be provided through environment variables/Kubernetes Secrets, not YAML: "
            f"{', '.join(secrets)}"
        )
    for key, value in config.items():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise SystemExit(f"Setting {key} in SIM_CONFIG_FILE must be a scalar value")
    return {
        key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in config.items()
        if value is not None
    }


def load_settings(config_file: Path | None = None) -> Settings:
    config_path = config_file or (
        Path(os.environ["SIM_CONFIG_FILE"]) if os.getenv("SIM_CONFIG_FILE") else None
    )
    source: dict[str, Any] = _yaml_config(config_path) if config_path else {}
    source.update(os.environ)
    get = source.get
    env = str(get("SIM_ENV", "dev"))
    auth_mode = str(
        get("SIM_AUTH_MODE", "required" if env.lower() in {"prod", "production"} else "dev")
    )
    settings = Settings(
        env=env,
        database_url=_default_database_url(source),
        data_dir=_data_dir(source),
        auth_mode=auth_mode,
        tokens=_tokens(get("SIM_API_TOKENS", "")),
        worker_id=str(get("SIM_WORKER_ID", "local-1")),
        executor_backend=str(get("SIM_EXECUTOR", "local")),
        worker_cpu=int(get("SIM_WORKER_CPU", "64")),
        worker_mem_gb=int(get("SIM_WORKER_MEM_GB", "256")),
        worker_gpu=int(get("SIM_WORKER_GPU", "4")),
        scheduler_enabled=str(get("SIM_SCHEDULER_ENABLED", "1")).lower()
        not in {"0", "false", "no"},
        scheduler_tick_sec=float(get("SIM_SCHEDULER_TICK_SEC", "0.5")),
        scheduler_batch=int(get("SIM_SCHEDULER_BATCH", "50")),
        aging_sec=int(get("SIM_AGING_SEC", "60")),
        heartbeat_timeout_sec=int(get("SIM_HEARTBEAT_TIMEOUT_SEC", "30")),
        reconcile_sec=int(get("SIM_RECONCILE_SEC", "30")),
        expand_batch=int(get("SIM_EXPAND_BATCH", "1000")),
        sync_expand_limit=int(get("SIM_SYNC_EXPAND_LIMIT", "500")),
        seed=int(get("SIM_SEED", "7")),
        account_auth=str(get("SIM_ACCOUNT_AUTH", "1")).lower() not in {"0", "false", "no"},
        serve_frontend=str(get("SIM_SERVE_FRONTEND", "1")).lower() not in {"0", "false", "no"},
        object_store_bucket=str(get("SIM_OBJECT_STORE_BUCKET", "")),
        object_store_endpoint_url=get("SIM_OBJECT_STORE_ENDPOINT_URL") or None,
        object_store_region=get("SIM_OBJECT_STORE_REGION") or None,
        object_store_access_key=get("SIM_OBJECT_STORE_ACCESS_KEY") or None,
        object_store_secret_key=get("SIM_OBJECT_STORE_SECRET_KEY") or None,
        object_store_prefix=str(get("SIM_OBJECT_STORE_PREFIX", f"sim/{env.lower()}")),
        worker_api_url=str(get("SIM_WORKER_API_URL", "")),
        worker_token=str(get("SIM_WORKER_TOKEN", "")),
        worker_poll_sec=float(get("SIM_WORKER_POLL_SEC", "2")),
        worker_heartbeat_sec=float(get("SIM_WORKER_HEARTBEAT_SEC", "10")),
        k8s_namespace=str(get("SIM_K8S_NAMESPACE", f"sim-{env.lower()}")),
        k8s_worker_image=str(get("SIM_K8S_WORKER_IMAGE", "")),
        k8s_worker_secret_name=str(get("SIM_K8S_WORKER_SECRET_NAME", "sim-worker-secrets")),
        k8s_service_account=get("SIM_K8S_SERVICE_ACCOUNT") or None,
        k8s_image_pull_secret=get("SIM_K8S_IMAGE_PULL_SECRET") or None,
        k8s_pool_name=str(get("SIM_K8S_POOL_NAME", f"sim-worker-{env.lower()}")),
        k8s_pool_replicas=int(get("SIM_K8S_POOL_REPLICAS", "2")),
        k8s_worker_slots=int(get("SIM_K8S_WORKER_SLOTS", "1")),
        k8s_slot_cpu=int(get("SIM_K8S_SLOT_CPU", "1")),
        k8s_slot_mem_gb=int(get("SIM_K8S_SLOT_MEM_GB", "1")),
        k8s_slot_gpu=int(get("SIM_K8S_SLOT_GPU", "0")),
        kubeconfig=get("KUBECONFIG") or None,
    )
    settings.validate()
    return settings
