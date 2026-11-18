"""FastAPI application assembly."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api import auth, metrics, playback, scenarios, sets, system, tasks, users, worker
from backend.api.errors import install_handlers
from backend.playback.service import PlaybackService
from backend.scenario.metrics_service import MetricService
from backend.scenario.service import ScenarioService
from backend.scenario.sets import SetService
from backend.shared.config import Settings, load_settings
from backend.shared.db import Database
from backend.shared.files import FileStore
from backend.shared.object_store import S3FileStore, create_s3_client
from backend.sim.executor import LocalExecutor
from backend.sim.executor_protocol import Executor
from backend.sim.expander import Expander
from backend.sim.k8s_executor import K8sJobExecutor, K8sPoolExecutor
from backend.sim.results import ResultService
from backend.sim.scheduler import Scheduler
from backend.sim.service import TaskService
from backend.sim.worker_service import WorkerService

LOG = logging.getLogger("sim.app")
ROUTERS = (
    system.router,
    auth.router,
    users.router,
    scenarios.router,
    sets.router,
    metrics.router,
    tasks.router,
    worker.router,
    playback.router,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or load_settings()
    (
        db, store, scenario_service, set_service, metric_service, task_service,
        playback_service, results, expander, executor, scheduler,
    ) = _build_services(config)
    worker_service = WorkerService(db, results, config)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if config.scheduler_enabled and not db.is_postgres:
            raise RuntimeError("scheduler requires PostgreSQL; set SIM_SCHEDULER_ENABLED=0 for SQLite dev")
        if db.is_postgres:
            await scenario_service.recover_pending()
            await set_service.recover_pending()
            await playback_service.recover_pending()
        if config.scheduler_enabled:
            await scheduler.start()
        try:
            yield
        finally:
            await scheduler.stop()
            await db.close()

    app = FastAPI(title="SimCloud", version="2.0.0", lifespan=lifespan)
    state = {
        "settings": config, "db": db, "store": store, "scenario_service": scenario_service,
        "set_service": set_service, "metric_service": metric_service, "task_service": task_service,
        "playback_service": playback_service, "results": results, "expander": expander,
        "executor": executor, "scheduler": scheduler,
        "worker_service": worker_service,
    }
    for key, value in state.items():
        setattr(app.state, key, value)

    install_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in ROUTERS:
        app.include_router(router, prefix="/api")

    if config.serve_frontend:
        _mount_frontend(app, config)
    return app


def _build_services(
    config: Settings,
) -> tuple[
    Database, FileStore, ScenarioService, SetService, MetricService, TaskService,
    PlaybackService, ResultService, Expander, Executor, Scheduler,
]:
    db = Database(config.database_url)
    if config.object_store_bucket:
        store: FileStore = S3FileStore(
            config.data_dir,
            client=create_s3_client(
                endpoint_url=config.object_store_endpoint_url,
                region=config.object_store_region,
                access_key=config.object_store_access_key,
                secret_key=config.object_store_secret_key,
            ),
            bucket=config.object_store_bucket,
            prefix=config.object_store_prefix,
        )
    else:
        store = FileStore(config.data_dir)
    scenario_service = ScenarioService(db, store)
    set_service = SetService(db, store)
    metric_service = MetricService(db)
    task_service = TaskService(
        db,
        set_service,
        sync_limit=config.sync_expand_limit,
        store=store,
        require_binary_uri=config.executor_backend.startswith("k8s_"),
    )
    playback_service = PlaybackService(db, store)
    results = ResultService(db, heartbeat_timeout_sec=config.heartbeat_timeout_sec)
    expander = Expander(db, set_service, batch=config.expand_batch)
    if config.executor_backend == "k8s_pool":
        executor: Executor = K8sPoolExecutor(db, config)
    elif config.executor_backend == "k8s_job":
        executor = K8sJobExecutor(db, config)
    else:
        executor = LocalExecutor(db, results, config)
    scheduler = Scheduler(db, config, results, expander, executor)
    return (
        db, store, scenario_service, set_service, metric_service, task_service,
        playback_service, results, expander, executor, scheduler,
    )


def _mount_frontend(app: FastAPI, config: Settings) -> None:
    dist = config.data_dir.parent / "frontend" / "app" / "dist"
    if not dist.exists():
        return
    app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
