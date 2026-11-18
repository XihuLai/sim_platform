"""Kubernetes pooled-worker implementation of the Executor contract."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.shared.config import Settings
from backend.shared.db import Database


class K8sPoolExecutor:
    """Maintain long-running worker Pods that claim durable DB outbox entries."""

    name = "k8s_pool"
    dispatch_mode = "pull"
    supports_pause = True

    def __init__(
        self,
        db: Database,
        settings: Settings,
        *,
        apps_api: Any | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.apps_api = apps_api
        self._statuses: dict[str, str] = {}

    def _apps_api(self) -> Any:
        if self.apps_api is not None:
            return self.apps_api
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
        self.apps_api = self.apps_api or client.AppsV1Api()
        return self.apps_api

    def _pod_spec(self) -> dict[str, Any]:
        container: dict[str, Any] = {
            "name": "worker",
            "image": self.settings.k8s_worker_image,
            "imagePullPolicy": "IfNotPresent",
            "env": [
                {"name": "SIM_WORK_MODE", "value": "poll"},
                {"name": "SIM_WORKER_API_URL", "value": self.settings.worker_api_url.rstrip("/")},
                {"name": "SIM_WORKER_SLOTS", "value": str(self.settings.k8s_worker_slots)},
                {
                    "name": "SIM_WORKER_CPU",
                    "value": str(self.settings.k8s_slot_cpu * self.settings.k8s_worker_slots),
                },
                {
                    "name": "SIM_WORKER_MEM_GB",
                    "value": str(self.settings.k8s_slot_mem_gb * self.settings.k8s_worker_slots),
                },
                {
                    "name": "SIM_WORKER_GPU",
                    "value": str(self.settings.k8s_slot_gpu * self.settings.k8s_worker_slots),
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
            "resources": self._resources(),
        }
        pod: dict[str, Any] = {
            "restartPolicy": "Always",
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

    def _resources(self) -> dict[str, dict[str, str]]:
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

    async def close(self) -> None:
        return

    def status(self, case_run_id: str) -> str:
        return self._statuses.get(case_run_id, "unknown")

    async def start(self) -> None:
        apps_api = self._apps_api()
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
                    "spec": self._pod_spec(),
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
