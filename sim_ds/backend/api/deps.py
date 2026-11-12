"""FastAPI dependency wiring."""

from __future__ import annotations

from fastapi import Request

from backend.playback.service import PlaybackService
from backend.scenario.metrics_service import MetricService
from backend.scenario.service import ScenarioService
from backend.scenario.sets import SetService
from backend.shared.auth import Principal, resolve_principal
from backend.shared.config import Settings
from backend.shared.db import Database
from backend.shared.files import FileStore
from backend.sim.service import TaskService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_db(request: Request) -> Database:
    return request.app.state.db  # type: ignore[no-any-return]


def get_store(request: Request) -> FileStore:
    return request.app.state.store  # type: ignore[no-any-return]


def get_principal(request: Request) -> Principal:
    settings: Settings = request.app.state.settings
    principal = resolve_principal(request, settings)
    request.state.principal = principal
    return principal


def get_scenarios(request: Request) -> ScenarioService:
    return request.app.state.scenario_service  # type: ignore[no-any-return]


def get_sets(request: Request) -> SetService:
    return request.app.state.set_service  # type: ignore[no-any-return]


def get_metrics(request: Request) -> MetricService:
    return request.app.state.metric_service  # type: ignore[no-any-return]


def get_tasks(request: Request) -> TaskService:
    return request.app.state.task_service  # type: ignore[no-any-return]


def get_playback(request: Request) -> PlaybackService:
    return request.app.state.playback_service  # type: ignore[no-any-return]
