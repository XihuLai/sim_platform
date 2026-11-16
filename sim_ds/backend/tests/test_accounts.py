from pathlib import Path

from backend.app import create_app
from backend.shared.config import Settings
from fastapi.testclient import TestClient


def test_super_admin_login_user_management_and_priority(
    postgres_url: str, clean: None, tmp_path: Path
) -> None:
    app = create_app(
        Settings(database_url=postgres_url, data_dir=tmp_path, scheduler_enabled=False, auth_mode="dev")
    )
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "df_sim", "password": "df@sim_007"})
        assert login.status_code == 200
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        me = client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200 and me.json()["role"] == "super_admin"

        created = client.post(
            "/api/users",
            headers=headers,
            json={
                "username": "operator_test",
                "password": "operator_123",
                "display_name": "操作员",
                "role": "user",
                "max_priority": 3,
                "max_running_cases": 10,
                "max_cpu": 8,
                "max_mem_gb": 16,
                "max_gpu": 0,
            },
        )
        assert created.status_code == 201
        user = created.json()
        assert user["max_priority"] == 3

        updated = client.put(
            f"/api/users/{user['id']}",
            headers=headers,
            json={"max_priority": 2, "display_name": "操作员-2"},
        )
        assert updated.status_code == 200 and updated.json()["max_priority"] == 2

        operator_login = client.post(
            "/api/auth/login", json={"username": "operator_test", "password": "operator_123"}
        )
        assert operator_login.status_code == 200
        operator_headers = {"Authorization": f"Bearer {operator_login.json()['token']}"}
        operator_me = client.get("/api/auth/me", headers=operator_headers).json()
        assert operator_me["max_priority"] == 2
        assert operator_me["admin"] is False

        forbidden = client.post(
            "/api/metrics/defs",
            headers=operator_headers,
            json={"id": "demo.metric", "version": 1, "type_id": "safety.brake", "name": "demo"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "FORBIDDEN"
