"""Kubernetes Job and pooled-worker implementations of the Executor contract."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from backend.scenario.common import loads
from backend.shared.config import Settings
from backend.shared.db import Database


class KubernetesExecutorBase:
    name: str
    dispatch_mode: str
    supports_pause = False

    def __init__(
        self,
        db: Database,
        settings: Settings,
        *,
        batch_api: Any | None = None,
        apps_api: Any | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.batch_api = batch_api
        self.apps_api = apps_api
        self._statuses: dict[str, str] = {}

    def _apis(self) -> tuple[Any, Any, Any]:
        if self.batch_api is not None and (self.apps_api is not None or not self.name.endswith("pool")):
            return self.batch_api, self.apps_api, None
        try:
            from kubernetes import client, config
            from kubernetes.config.config_exception import ConfigException
        except ImportError as exc:
            raise RuntimeError("Kubernetes executors require the 'k8s' optional dependencies") from exc
        if self.settings.kubeconfig:
            config.load_kube_config(config_file=self.settings.kubeconfig)
        else:
            try:
                config.load_incluster_config()
            except ConfigException:
                config.load_kube_config()
        self.batch_api = self.batch_api or client.BatchV1Api()
        self.apps_api = self.apps_api or client.AppsV1Api()
        return self.batch_api, self.apps_api, client

    async def _case_spec(self, case_run_id: str) -> dict[str, Any]:
        row = await self.db.fetch_one(
            """
            SELECT c.id AS case_run_id, c.task_id, c.scenario_id, c.scenario_version,
                   c.attempt, c.priority, c.resource_req, t.runtime_config, t.seed,
                   v.file_uri AS scenario_uri, v.file_checksum AS scenario_checksum
            FROM case_run c
            JOIN sim_task t ON t.id=c.task_id
            JOIN scenario_version v
              ON v.scenario_id=c.scenario_id AND v.version=c.scenario_version
            WHERE c.id=:id
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            {"id": case_run_id},
        )
        if row is None:
            raise LookupError(f"CaseRun {case_run_id} was not found")
        runtime = loads(row["runtime_config"])
        if not str(row["scenario_uri"]).startswith("s3://"):
            raise ValueError("Kubernetes workers require scenario versions published to s3://")
        if not str(runtime.get("binary_uri", "")).startswith("s3://"):
            raise ValueError("Kubernetes workers require RuntimeConfig.binary_uri (s3://)")
        return {
            "case_run_id": row["case_run_id"],
            "task_id": row["task_id"],
            "scenario_id": row["scenario_id"],
            "scenario_version": row["scenario_version"],
            "attempt": row["attempt"],
            "priority": row["priority"],
            "resource": loads(row["resource_req"]) or {},
            "runtime": runtime,
            "seed": row["seed"],
            "scenario_uri": row["scenario_uri"],
            "scenario_checksum": row["scenario_checksum"],
        }

    def _pod_spec(self, *, mode: str, work_spec: dict[str, Any] | None = None) -> dict[str, Any]:
        container: dict[str, Any] = {
            "name": "worker",
            "image": self.settings.k8s_worker_image,
            "imagePullPolicy": "IfNotPresent",
            "env": [
                {"name": "SIM_WORK_MODE", "value": mode},
                {"name": "SIM_WORKER_API_URL", "value": self.settings.worker_api_url.rstrip("/")},
                {"name": "SIM_WORKER_SLOTS", "value": str(self.settings.k8s_worker_slots)},
                {
                    "name": "SIM_WORKER_CPU",
                    "value": str(
                        self.settings.k8s_slot_cpu * self.settings.k8s_worker_slots
                        if mode == "poll"
                        else 1
                    ),
                },
                {
                    "name": "SIM_WORKER_MEM_GB",
                    "value": str(
                        self.settings.k8s_slot_mem_gb * self.settings.k8s_worker_slots
                        if mode == "poll"
                        else 1
                    ),
                },
                {
                    "name": "SIM_WORKER_GPU",
                    "value": str(
                        self.settings.k8s_slot_gpu * self.settings.k8s_worker_slots
                        if mode == "poll"
                        else 0
                    ),
                },
                {"name": "SIM_OBJECT_STORE_BUCKET", "value": self.settings.object_store_bucket},
                {"name": "SIM_OBJECT_STORE_PREFIX", "value": self.settings.object_store_prefix},
                {
                    "name": "POD_NAME",
                    "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}},
                },
                {
                    "name": "SIM_OBJECT_STORE_ENDPOINT_URL",
                    "value": self.settings.object_store_endpoint_url or "",
                },
                {"name": "SIM_OBJECT_STORE_REGION", "value": self.settings.object_store_region or ""},
            ],
            "envFrom": [{"secretRef": {"name": self.settings.k8s_worker_secret_name}}],
            "resources": self._resources(mode=mode, work_spec=work_spec),
        }
        if work_spec is not None:
            container["env"].append(
                {"name": "SIM_WORK_SPEC", "value": json.dumps(work_spec, separators=(",", ":"))}
            )
        pod: dict[str, Any] = {
            "restartPolicy": "Never" if mode == "single" else "Always",
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [container],
        }
        if self.settings.k8s_service_account:
            pod["serviceAccountName"] = self.settings.k8s_service_account
        if self.settings.k8s_image_pull_secret:
            pod["imagePullSecrets"] = [{"name": self.settings.k8s_image_pull_secret}]
        return pod

    def _resources(
        self, *, mode: str, work_spec: dict[str, Any] | None
    ) -> dict[str, dict[str, str]]:
        if mode == "single":
            requested = (work_spec or {}).get("resource") or {}
            cpu = int(requested.get("cpu", 1))
            mem_gb = int(requested.get("mem_gb", 1))
            gpu = int(requested.get("gpu", 0))
        else:
            cpu = self.settings.k8s_slot_cpu * self.settings.k8s_worker_slots
            mem_gb = self.settings.k8s_slot_mem_gb * self.settings.k8s_worker_slots
            gpu = self.settings.k8s_slot_gpu * self.settings.k8s_worker_slots
        requests = {
            "cpu": str(max(1, cpu)),
            "memory": f"{max(1, mem_gb)}Gi",
        }
        limits = dict(requests)
        if gpu:
            requests["nvidia.com/gpu"] = str(gpu)
            limits["nvidia.com/gpu"] = str(gpu)
        return {"requests": requests, "limits": limits}

    async def _get_case_status(self, case_run_id: str) -> str:
        row = await self.db.fetch_one(
            "SELECT status FROM case_run WHERE id=:id ORDER BY created_at DESC LIMIT 1",
            {"id": case_run_id},
        )
        return str(row["status"]) if row else "unknown"

    async def start(self) -> None:
        return

    async def close(self) -> None:
        return

    async def pause(self, case_run_id: str) -> bool:
        return False

    async def resume(self, case_run_id: str) -> bool:
        return False

    def status(self, case_run_id: str) -> str:
        return self._statuses.get(case_run_id, "unknown")

    def _job_name(self, case_run_id: str, attempt: int) -> str:
        clean = re.sub(r"[^a-z0-9-]", "-", case_run_id.lower()).strip("-")
        return f"sim-{clean[:40]}-a{attempt}"[:63].rstrip("-")


class K8sJobExecutor(KubernetesExecutorBase):
    """Create one short-lived Kubernetes Job for each CaseRun attempt."""

    name = "k8s_job"
    supports_pause = False

    async def submit(self, case: dict[str, Any]) -> None:
        case_id = str(case["id"])
        spec = await self._case_spec(case_id)
        batch_api, _, _ = self._apis()
        name = self._job_name(case_id, int(spec["attempt"]))
        labels = {
            "app.kubernetes.io/name": "sim-worker",
            "sim-platform/case-run-id": _label_value(case_id),
            "sim-platform/attempt": str(spec["attempt"]),
        }
        body = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": name, "namespace": self.settings.k8s_namespace, "labels": labels},
            "spec": {
                "backoffLimit": 0,
                "ttlSecondsAfterFinished": 3600,
                "activeDeadlineSeconds": int(spec["runtime"]["timeout_sec"]) + 180,
                "template": {
                    "metadata": {"labels": labels},
                    "spec": self._pod_spec(mode="single", work_spec=spec),
                },
            },
        }
        await asyncio.to_thread(
            batch_api.create_namespaced_job,
            namespace=self.settings.k8s_namespace,
            body=body,
        )
        self._statuses[case_id] = "submitted"

    async def cancel(self, case_run_id: str) -> bool:
        batch_api, _, _ = self._apis()
        row = await self.db.fetch_one(
            "SELECT attempt FROM case_run WHERE id=:id ORDER BY created_at DESC LIMIT 1",
            {"id": case_run_id},
        )
        if row is None:
            return False
        name = self._job_name(case_run_id, int(row["attempt"]))
        try:
            from kubernetes.client.exceptions import ApiException
        except ImportError as exc:
            raise RuntimeError("Kubernetes executors require the 'k8s' optional dependencies") from exc
        try:
            await asyncio.to_thread(
                batch_api.delete_namespaced_job,
                name=name,
                namespace=self.settings.k8s_namespace,
                body={"propagationPolicy": "Foreground"},
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
        self._statuses[case_run_id] = "canceled"
        return True


class K8sPoolExecutor(KubernetesExecutorBase):
    """Maintain long-running worker Pods that claim durable DB outbox entries."""

    name = "k8s_pool"
    supports_pause = True
    dispatch_mode = "pull"

    async def start(self) -> None:
        _, apps_api, _ = self._apis()
        labels = {"app.kubernetes.io/name": "sim-worker", "sim-platform/pool": self.settings.k8s_pool_name}
        body = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": self.settings.k8s_pool_name,
                "namespace": self.settings.k8s_namespace,
                "labels": labels,
            },
            "spec": {
                "replicas": self.settings.k8s_pool_replicas,
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": self._pod_spec(mode="poll"),
                },
            },
        }
        try:
            from kubernetes.client.exceptions import ApiException
        except ImportError as exc:
            raise RuntimeError("Kubernetes executors require the 'k8s' optional dependencies") from exc
        try:
            await asyncio.to_thread(
                apps_api.read_namespaced_deployment,
                name=self.settings.k8s_pool_name,
                namespace=self.settings.k8s_namespace,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
            await asyncio.to_thread(
                apps_api.create_namespaced_deployment,
                namespace=self.settings.k8s_namespace,
                body=body,
            )
        else:
            await asyncio.to_thread(
                apps_api.patch_namespaced_deployment,
                name=self.settings.k8s_pool_name,
                namespace=self.settings.k8s_namespace,
                body=body,
            )

    async def submit(self, case: dict[str, Any]) -> None:
        case_id = str(case["id"])
        self._statuses[case_id] = "scheduled"

    async def pause(self, case_run_id: str) -> bool:
        return await self._get_case_status(case_run_id) in {"running", "scheduled", "paused"}

    async def resume(self, case_run_id: str) -> bool:
        return await self._get_case_status(case_run_id) == "paused"

    async def cancel(self, case_run_id: str) -> bool:
        return await self._get_case_status(case_run_id) in {
            "running",
            "scheduled",
            "paused",
            "canceled",
        }


def _label_value(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]", "-", value)
    return clean[:63].strip("-_.") or "case"
