from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from backend.shared.config import Settings
from backend.shared.db import dumps
from backend.shared.errors import AppError
from backend.shared.object_store import S3FileStore
from backend.sim.k8s_executor import K8sJobExecutor, K8sPoolExecutor
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


class FakeBatchApi:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def create_namespaced_job(self, *, namespace: str, body: dict[str, Any]) -> None:
        self.jobs.append(body)

    def delete_namespaced_job(self, *, name: str, namespace: str, body: dict[str, Any]) -> None:
        self.deleted.append(name)


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


@pytest.mark.asyncio
async def test_k8s_job_executor_creates_single_case_job(tmp_path: Path) -> None:
    api = FakeBatchApi()
    executor = K8sJobExecutor(
        FakeDatabase(), _settings(tmp_path), batch_api=api
    )  # type: ignore[arg-type]

    await executor.submit({"id": "run-1"})

    job = api.jobs[0]
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert job["spec"]["backoffLimit"] == 0
    assert job["spec"]["template"]["spec"]["restartPolicy"] == "Never"
    assert container["resources"]["requests"] == {"cpu": "2", "memory": "3Gi"}
    assert any(item["name"] == "SIM_WORK_SPEC" for item in container["env"])
    assert container["envFrom"] == [{"secretRef": {"name": "worker-secrets"}}]
    assert "volumes" not in job["spec"]["template"]["spec"]


@pytest.mark.asyncio
async def test_k8s_pool_executor_creates_secure_pull_deployment(tmp_path: Path) -> None:
    apps = FakeAppsApi()
    executor = K8sPoolExecutor(
        FakeDatabase(), _settings(tmp_path), batch_api=FakeBatchApi(), apps_api=apps
    )  # type: ignore[arg-type]

    await executor.start()

    assert apps.deployment is not None
    pod = apps.deployment["spec"]["template"]["spec"]
    assert apps.deployment["spec"]["replicas"] == 2
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["containers"][0]["env"][0] == {"name": "SIM_WORK_MODE", "value": "poll"}
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
