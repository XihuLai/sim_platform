from pathlib import Path

from backend.app import create_app
from backend.shared.config import Settings
from fastapi.testclient import TestClient


def app_settings(postgres_url: str, tmp_path: Path) -> Settings:
    return Settings(
        database_url=postgres_url,
        data_dir=tmp_path,
        scheduler_enabled=False,
        auth_mode="dev",
    )


def test_health_and_catalog_endpoints(postgres_url: str, clean: None, tmp_path: Path) -> None:
    app = create_app(app_settings(postgres_url, tmp_path))
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200 and health.json()["status"] == "ok"
        categories = client.get("/api/metrics/categories")
        assert categories.status_code == 200
        assert len(categories.json()["items"]) == 5
        templates = client.get("/api/metrics/templates")
        assert templates.status_code == 200 and templates.json()["items"]
        overview = client.get("/api/stats/overview")
        assert overview.status_code == 200 and overview.json()["scenarios"] == 0
        empty = client.get("/api/tasks?size=5")
        assert empty.status_code == 200 and empty.json()["items"] == []
        missing = client.get("/api/tasks/tsk_missing")
        assert missing.status_code == 404


def test_invalid_tag_returns_422(postgres_url: str, clean: None, tmp_path: Path) -> None:
    app = create_app(app_settings(postgres_url, tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/scenarios",
            json={
                "name": "非法标签",
                "source": {"type": "record"},
                "time_window": {"start_ts": 0, "end_ts": 1, "trigger_ts": 0},
                "tags": ["A&B"],
            },
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert body["detail"]["errors"][0]["ctx"]["error"]
