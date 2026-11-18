from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from backend.shared.config import Settings, load_settings
from backend.shared.db import dumps
from backend.shared.errors import AppError
from backend.shared.object_store import S3FileStore
from backend.sim.k8s_executor import K8sPoolExecutor
from backend.sim.worker import SchedulerWorkerClient, Worker
from botocore.exceptions import ClientError
from kubernetes.client.exceptions import ApiException


class MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        key = (kwargs["Bucket"], kwargs["Key"])
        if key in self.objects:
            raise ClientError({"ResponseMetadata": {"HTTPStatusCode": 412}}, "PutObject")
        self.objects[key] = bytes(kwargs["Body"])

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        try:
            body = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise ClientError({"ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject") from exc
        return {"Body": io.BytesIO(body)}

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        Path(destination).write_bytes(self.objects[(bucket, key)])

    def upload_file(self, source: str, bucket: str, key: str, ExtraArgs: dict[str, Any]) -> None:
        self.objects[(bucket, key)] = Path(source).read_bytes()


class FakeDatabase:
    def __init__(self) -> None:
        self.row = {
            "case_run_id": "run-1",
            "task_id": "task-1",
            "scenario_id": "scenario-1",
            "scenario_version": 1,
            "attempt": 2,
            "priority": 1,
            "resource_req": dumps({"cpu": 2, "mem_gb": 3, "gpu": 0}),
            "runtime_config": dumps(
                {
                    "binary_id": "engine",
                    "binary_uri": "s3://artifacts/engine",
                    "binary_checksum": "sha256:" + "a" * 64,
                    "timeout_sec": 120,
                }
            ),
            "seed": 7,
            "scenario_uri": "s3://artifacts/scenario.json",
            "scenario_checksum": "sha256:" + "b" * 64,
        }

    async def fetch_one(self, sql: str, params: dict[str, Any]) -> dict[str, Any]:
        return self.row


class FakeAppsApi:
    def __init__(self) -> None:
        self.deployment: dict[str, Any] | None = None

    def read_namespaced_deployment(self, *, name: str, namespace: str) -> dict[str, Any]:
        if self.deployment is None:
            raise ApiException(status=404)
        return self.deployment

    def create_namespaced_deployment(self, *, namespace: str, body: dict[str, Any]) -> None:
        self.deployment = body

    def patch_namespaced_deployment(
        self, *, name: str, namespace: str, body: dict[str, Any]
    ) -> None:
        self.deployment = body


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        k8s_namespace="sim",
        k8s_worker_image="registry.invalid/sim-worker:test",
        k8s_worker_secret_name="worker-secrets",
        object_store_bucket="artifacts",
        worker_api_url="https://scheduler.invalid/api",
        worker_token="worker-secret",
        worker_cpu=8,
        worker_mem_gb=16,
        worker_gpu=0,
    )


def test_k8s_worker_pool_defaults_to_one_slot(tmp_path: Path) -> None:
    assert Settings(data_dir=tmp_path).k8s_worker_slots == 1


def test_k8s_job_executor_backend_is_rejected(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, executor_backend="k8s_job")

    with pytest.raises(SystemExit, match="SIM_EXECUTOR must be local or k8s_pool"):
        settings.validate()


def test_test_environment_uses_distinct_default_database_and_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIM_ENV", "test")
    monkeypatch.setenv("SIM_DATA_DIR", str(tmp_path))
    for name in (
        "SIM_DATABASE_URL",
        "SIM_PG_DATABASE",
        "SIM_K8S_NAMESPACE",
        "SIM_K8S_POOL_NAME",
        "SIM_OBJECT_STORE_PREFIX",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()

    assert settings.database_url.endswith("/sim_test")
    assert settings.k8s_namespace == "sim-test"
    assert settings.k8s_pool_name == "sim-worker-test"
    assert settings.object_store_prefix == "sim/test"


def test_load_settings_reads_yaml_and_environment_overrides_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "sim-test.yaml"
    config.write_text(
        "\n".join(
            [
                "SIM_ENV: test",
                "SIM_AUTH_MODE: required",
                "SIM_EXECUTOR: k8s_pool",
                "SIM_DATA_DIR: " + str(tmp_path / "data"),
                "SIM_K8S_NAMESPACE: sim-test",
                "SIM_K8S_WORKER_IMAGE: registry.example.com/sim/worker:test",
                "SIM_K8S_POOL_NAME: sim-worker-test",
                "SIM_K8S_POOL_REPLICAS: 1",
                "SIM_K8S_WORKER_SLOTS: 1",
                "SIM_OBJECT_STORE_BUCKET: sim-test-artifacts",
                "SIM_OBJECT_STORE_PREFIX: sim/test",
                "SIM_WORKER_API_URL: https://test.example.com/api",
                "SIM_SERVE_FRONTEND: false",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIM_WORKER_TOKEN", "injected-secret")
    monkeypatch.setenv("SIM_K8S_POOL_REPLICAS", "3")
    monkeypatch.setenv("SIM_CONFIG_FILE", str(config))

    settings = load_settings()

    assert settings.executor_backend == "k8s_pool"
    assert settings.k8s_namespace == "sim-test"
    assert settings.k8s_worker_image == "registry.example.com/sim/worker:test"
    assert settings.k8s_pool_name == "sim-worker-test"
    assert settings.k8s_pool_replicas == 3
    assert settings.k8s_worker_slots == 1
    assert settings.worker_token == "injected-secret"
    assert not settings.serve_frontend


def test_yaml_config_rejects_secret_values(tmp_path: Path) -> None:
    config = tmp_path / "unsafe.yaml"
    config.write_text("SIM_WORKER_TOKEN: do-not-store-here\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="Secrets must be provided"):
        load_settings(config)


@pytest.mark.asyncio
async def test_k8s_pool_executor_creates_secure_pull_deployment(tmp_path: Path) -> None:
    apps = FakeAppsApi()
    executor = K8sPoolExecutor(FakeDatabase(), _settings(tmp_path), apps_api=apps)  # type: ignore[arg-type]

    await executor.start()

    assert apps.deployment is not None
    pod = apps.deployment["spec"]["template"]["spec"]
    assert apps.deployment["spec"]["replicas"] == 2
    assert apps.deployment["metadata"]["namespace"] == "sim"
    assert apps.deployment["metadata"]["name"] == "sim-worker"
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["containers"][0]["image"] == "registry.invalid/sim-worker:test"
    assert pod["containers"][0]["env"][0] == {"name": "SIM_WORK_MODE", "value": "poll"}
    assert {"name": "SIM_WORKER_SLOTS", "value": "1"} in pod["containers"][0]["env"]
    assert pod["containers"][0]["resources"]["requests"] == {"cpu": "1", "memory": "1Gi"}
    assert "volumes" not in pod


@pytest.mark.asyncio
async def test_s3_file_store_publishes_immutably_and_verifies(tmp_path: Path) -> None:
    client = MemoryS3()
    store = S3FileStore(tmp_path, client=client, bucket="artifacts", prefix="platform")
    published = store.publish("scenarios/s1/v1.json", {"name": "scenario"})

    assert published.uri == "s3://artifacts/platform/scenarios/s1/v1.json"
    assert store.verify(published.uri, published.checksum)
    assert store.read_bytes(store.resolve(published.uri)) == b'{"name":"scenario"}'
    with pytest.raises(AppError, match="同名对象已存在"):
        store.publish("scenarios/s1/v1.json", {"name": "different"})


def test_s3_file_store_recovery_publishes_local_temp_to_object_store(tmp_path: Path) -> None:
    client = MemoryS3()
    store = S3FileStore(tmp_path, client=client, bucket="artifacts", prefix="platform")
    temp = tmp_path / "scenarios/s1/v2.json.tmp"
    temp.parent.mkdir(parents=True, exist_ok=True)
    temp.write_bytes(b'{"name":"recovered"}')

    recovered = store.recover_temp("scenarios/s1/v2.json")

    assert recovered is not None
    assert recovered.uri == "s3://artifacts/platform/scenarios/s1/v2.json"
    assert client.objects[("artifacts", "platform/scenarios/s1/v2.json")] == b'{"name":"recovered"}'
    assert store.verify(recovered.uri, recovered.checksum)


def test_s3_file_store_recovery_returns_canonical_uri_for_existing_remote_object(
    tmp_path: Path,
) -> None:
    client = MemoryS3()
    client.objects[("artifacts", "platform/scenarios/s1/v3.json")] = b'{"name":"existing"}'
    store = S3FileStore(tmp_path, client=client, bucket="artifacts", prefix="platform")

    recovered = store.recover_temp("scenarios/s1/v3.json")

    assert recovered is not None
    assert recovered.uri == "s3://artifacts/platform/scenarios/s1/v3.json"


@pytest.mark.asyncio
async def test_worker_downloads_binary_uploads_output_and_reports(tmp_path: Path) -> None:
    storage = MemoryS3()
    scenario = b'{"scenario_id":"scenario-1"}'
    binary = (
        b"#!/usr/bin/env python3\n"
        b"import json\n"
        b"print(json.dumps({'result':'pass','metrics':{'metric':{'value':1,'pass':True}}}))\n"
    )
    storage.objects[("artifacts", "scenario.json")] = scenario
    storage.objects[("artifacts", "engine")] = binary
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/start"):
            return httpx.Response(200, json={"accepted": True})
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"accepted": True, "action": "continue"})
        return httpx.Response(200, json={"accepted": True, "code": "COMMITTED"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    client = SchedulerWorkerClient("https://scheduler.invalid/api", "token", http)
    worker = Worker(
        client=client,
        store=S3FileStore(tmp_path / "cache", client=storage, bucket="artifacts"),
        worker_id="pod-1",
        work_root=tmp_path / "work",
    )
    scenario_checksum = "sha256:" + hashlib.sha256(scenario).hexdigest()
    binary_checksum = "sha256:" + hashlib.sha256(binary).hexdigest()
    spec = {
        "case_run_id": "run-1",
        "task_id": "task-1",
        "scenario_id": "scenario-1",
        "scenario_version": 1,
        "attempt": 0,
        "seed": 7,
        "scenario_uri": "s3://artifacts/scenario.json",
        "scenario_checksum": scenario_checksum,
        "worker_id": "pod-1",
        "runtime": {
            "binary_id": "engine",
            "binary_uri": "s3://artifacts/engine",
            "binary_checksum": binary_checksum,
            "timeout_sec": 10,
            "args": [],
            "env": {"OUTPUT_DIR": str(tmp_path / "output")},
        },
    }

    await worker.run_case(spec)

    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
        "start",
        "heartbeat",
        "result",
    ]
    report = json.loads(requests[-1].content)
    assert report["status"] == "succeeded"
    assert report["metrics"]["metric"] == {"value": 1, "pass": True}
    assert report["output_uri"].startswith("s3://artifacts/outputs/task-1/run-1/attempt-0/")
    await client.close()


@pytest.mark.asyncio
async def test_worker_reads_eval_result_when_binary_emits_no_json(tmp_path: Path) -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    worker = Worker(
        client=SchedulerWorkerClient("https://scheduler.invalid/api", "token", http),
        store=S3FileStore(tmp_path / "cache", client=MemoryS3(), bucket="artifacts"),
        worker_id="pod-1",
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "eval_result.json").write_text(
        json.dumps(
            {
                "result": "fail",
                "metrics": {
                    "metric": {
                        "pass": False,
                        "functions": {"f": {"value": 0.25}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert worker._result(1, b"", b"", output_dir) == (
        "succeeded",
        0,
        "metric_threshold_exceeded",
    )
    assert worker._metrics(b"", output_dir) == {"metric": {"value": 0.25, "pass": False}}
    await http.aclose()
