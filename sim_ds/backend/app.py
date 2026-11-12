"""FastAPI application assembly."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api import metrics, playback, scenarios, sets, system, tasks
from backend.api.errors import install_handlers
from backend.playback.service import PlaybackService
from backend.scenario.metrics_service import MetricService
from backend.scenario.service import ScenarioService
from backend.scenario.sets import SetService
from backend.shared.config import Settings, load_settings
from backend.shared.db import Database
from backend.shared.files import FileStore
from backend.sim.executor import LocalExecutor
from backend.sim.expander import Expander
from backend.sim.results import ResultService
from backend.sim.scheduler import Scheduler
from backend.sim.service import TaskService

LOG = logging.getLogger("sim.app")
ROUTERS = (system.router, scenarios.router, sets.router, metrics.router, tasks.router, playback.router)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or load_settings()
    (
        db, store, scenario_service, set_service, metric_service, task_service,
        playback_service, results, expander, executor, scheduler,
    ) = _build_services(config)

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

    _mount_frontend(app, config)
    return app


def _build_services(
    config: Settings,
) -> tuple[
    Database, FileStore, ScenarioService, SetService, MetricService, TaskService,
    PlaybackService, ResultService, Expander, LocalExecutor, Scheduler,
]:
    db = Database(config.database_url)
    store = FileStore(config.data_dir)
    scenario_service = ScenarioService(db, store)
    set_service = SetService(db, store)
    metric_service = MetricService(db)
    task_service = TaskService(db, set_service, sync_limit=config.sync_expand_limit, store=store)
    playback_service = PlaybackService(db, store)
    results = ResultService(db, heartbeat_timeout_sec=config.heartbeat_timeout_sec)
    expander = Expander(db, set_service, batch=config.expand_batch)
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
