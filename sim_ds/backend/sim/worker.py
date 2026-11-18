"""Stateless Kubernetes worker: claim via Scheduler, use S3, report facts by HTTP."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
import socket
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from backend.shared.config import load_settings
from backend.shared.errors import AppError
from backend.shared.object_store import S3FileStore, create_s3_client

LOG = logging.getLogger("sim.worker")
_SAFE_ENV = {"SIM_SEED", "LOG_LEVEL", "SCENARIO_ID", "TASK_ID", "CASE_RUN_ID", "SIM_ENGINE"}


class SchedulerWorkerClient:
    def __init__(
        self, api_url: str, token: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self.api_url = api_url.rstrip("/") + "/internal/worker"
        self.token = token
        self.client = client or httpx.AsyncClient(timeout=30)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(4):
            try:
                response = await self.client.post(
                    self.api_url + path,
                    json=body,
                    headers={"Authorization": f"Bearer {self.token}"},
                )
            except httpx.TransportError:
                if attempt == 3:
                    raise
                await asyncio.sleep(min(2**attempt, 8))
                continue
            if response.status_code >= 500 and attempt < 3:
                await asyncio.sleep(min(2**attempt, 8))
                continue
            response.raise_for_status()
            break
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Scheduler returned an invalid response for {path}")
        return payload

    async def claim(self, worker_id: str, capacity: dict[str, int]) -> dict[str, Any] | None:
        result = await self._post("/claim", {"worker_id": worker_id, "capacity": capacity})
        case = result.get("case")
        return case if isinstance(case, dict) else None

    async def start(self, case: dict[str, Any]) -> bool:
        result = await self._post(
            "/start",
            {
                "case_run_id": case["case_run_id"],
                "attempt": case["attempt"],
                "worker_id": case["worker_id"],
            },
        )
        return bool(result.get("accepted"))

    async def heartbeat(self, case: dict[str, Any]) -> dict[str, Any]:
        return await self._post(
            "/heartbeat",
            {
                "case_run_id": case["case_run_id"],
                "attempt": case["attempt"],
                "worker_id": case["worker_id"],
            },
        )

    async def report(self, case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        return await self._post(
            "/result",
            {
                "case_run_id": case["case_run_id"],
                "attempt": case["attempt"],
                "worker_id": case["worker_id"],
                **result,
            },
        )


class Worker:
    def __init__(
        self,
        *,
        client: SchedulerWorkerClient,
        store: S3FileStore,
        worker_id: str,
        slots: int = 1,
        poll_sec: float = 2,
        heartbeat_sec: float = 10,
        work_root: Path | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.worker_id = worker_id
        self.slots = max(1, slots)
        self.poll_sec = max(0.1, poll_sec)
        self.heartbeat_sec = max(1, heartbeat_sec)
        self.work_root = work_root or Path(tempfile.gettempdir()) / "sim-worker"
        self._stop = asyncio.Event()
        self._active: set[asyncio.Task[None]] = set()

    async def run(self, work_spec: dict[str, Any] | None = None) -> None:
        if work_spec is not None:
            await self.run_case(work_spec)
            return
        capacity = {
            "cpu": int(os.getenv("SIM_WORKER_CPU", "1")),
            "mem_gb": int(os.getenv("SIM_WORKER_MEM_GB", "1")),
            "gpu": int(os.getenv("SIM_WORKER_GPU", "0")),
        }
        while not self._stop.is_set():
            completed = {task for task in self._active if task.done()}
            self._active.difference_update(completed)
            for task in completed:
                await task
            if len(self._active) >= self.slots:
                await asyncio.sleep(self.poll_sec)
                continue
            case = await self.client.claim(self.worker_id, capacity)
            if case is None:
                await asyncio.sleep(self.poll_sec)
                continue
            case["worker_id"] = self.worker_id
            task = asyncio.create_task(self.run_case(case))
            self._active.add(task)
        if self._active:
            await asyncio.gather(*self._active, return_exceptions=True)

    async def stop(self) -> None:
        self._stop.set()
        for task in self._active:
            task.cancel()

    async def run_case(self, case: dict[str, Any]) -> None:
        case = dict(case)
        case["worker_id"] = self.worker_id
        accepted = await self.client.start(case)
        if not accepted:
            LOG.info("ignoring stale worker claim %s", case["case_run_id"])
            return
        runtime = case["runtime"]
        attempt = int(case["attempt"])
        work_dir = (
            self.work_root
            / _work_segment(str(case["task_id"]))
            / _work_segment(str(case["case_run_id"]))
            / str(attempt)
        )
        input_dir = work_dir / "input"
        output_dir = work_dir / "output"
        log_dir = work_dir / "logs"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        scenario_path = input_dir / "scenario.json"
        self.store.download_to_file(
            case["scenario_uri"], scenario_path, case.get("scenario_checksum")
        )
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        source = scenario.get("source") or {}
        log_uri = str(source.get("log_uri") or "")
        if log_uri:
            if not log_uri.startswith("s3://"):
                raise AppError(
                    "SCENARIO_INPUT_URI_INVALID",
                    "Worker 场景日志必须使用 s3:// URI",
                    status=422,
                )
            log_path = input_dir / "scenario-source.log"
            self.store.download_to_file(log_uri, log_path, source.get("log_checksum") or None)
            source["log_uri"] = str(log_path)
            scenario["source"] = source
            scenario_path.write_text(
                json.dumps(scenario, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        binary_uri = runtime.get("binary_uri")
        if not isinstance(binary_uri, str) or not binary_uri.startswith("s3://"):
            raise AppError("BINARY_URI_REQUIRED", "Kubernetes Worker 需要 s3:// binary_uri", status=422)
        binary_path = input_dir / "engine"
        self.store.download_to_file(binary_uri, binary_path, runtime.get("binary_checksum"))
        binary_path.chmod(0o755)
        command = self._command(runtime, case, binary_path, scenario_path, output_dir)
        env = self._environment(runtime, case, scenario_path, output_dir, log_dir)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(output_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        monitor = asyncio.create_task(self._monitor(case, process))
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=int(runtime["timeout_sec"])
            )
        except asyncio.CancelledError:
            _signal_process(process, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                _signal_process(process, signal.SIGKILL)
            raise
        except TimeoutError:
            _signal_process(process, signal.SIGKILL)
            stdout, stderr = await process.communicate()
            status, exit_code, reason = "timeout", -1, f"timeout:{runtime['timeout_sec']}s"
        else:
            if monitor.done():
                await monitor
            state = await self.client.heartbeat(case)
            if state.get("action") in {"cancel", "stop"}:
                monitor.cancel()
                return
            status, exit_code, reason = self._result(
                process.returncode or 0, stdout, stderr, output_dir
            )
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        output_uri = self.store.upload_tree(
            output_dir, self._output_uri(case, attempt)
        )
        report_id = "rep-" + hashlib.sha256(
            f"{case['case_run_id']}:{attempt}:{status}".encode()
        ).hexdigest()[:24]
        result = await self.client.report(
            case,
            {
                "report_id": report_id,
                "status": status,
                "metrics": self._metrics(stdout, output_dir),
                "exit_code": exit_code,
                "reason": reason,
                "output_uri": output_uri,
            },
        )
        if not result.get("accepted"):
            LOG.warning("Scheduler rejected result report %s: %s", report_id, result)

    async def _monitor(self, case: dict[str, Any], process: asyncio.subprocess.Process) -> None:
        paused = False
        while process.returncode is None:
            await asyncio.sleep(self.heartbeat_sec)
            result = await self.client.heartbeat(case)
            action = result.get("action")
            if action in {"cancel", "stop"}:
                _signal_process(process, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except TimeoutError:
                    _signal_process(process, signal.SIGKILL)
                return
            if action == "pause" and not paused:
                _signal_process(process, signal.SIGSTOP)
                paused = True
            elif action == "continue" and paused:
                _signal_process(process, signal.SIGCONT)
                paused = False

    def _command(
        self,
        runtime: dict[str, Any],
        case: dict[str, Any],
        binary_path: Path,
        scenario_path: Path,
        output_dir: Path,
    ) -> list[str]:
        values = {
            "SCENARIO_URI": str(scenario_path),
            "OUTPUT_DIR": str(output_dir),
            "SEED": str(runtime.get("env", {}).get("SIM_SEED", case.get("seed") or 0)),
            "LOG_DIR": str(self.work_root / _work_segment(str(case["task_id"])) / "logs"),
        }
        args = [self._substitute(str(arg), values) for arg in runtime.get("args", [])]
        return [str(binary_path), *args] if args else [
            str(binary_path), "--scenario", str(scenario_path), "--out", str(output_dir),
            "--seed", values["SEED"],
        ]

    def _output_uri(self, case: dict[str, Any], attempt: int) -> str:
        parts = [self.store.prefix, "outputs"] if self.store.prefix else ["outputs"]
        parts.extend(
            _object_segment(str(case[key])) for key in ("task_id", "case_run_id")
        )
        parts.append(f"attempt-{attempt}")
        return f"s3://{self.store.bucket}/{'/'.join(parts)}"

    def _environment(
        self,
        runtime: dict[str, Any],
        case: dict[str, Any],
        scenario_path: Path,
        output_dir: Path,
        log_dir: Path,
    ) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
        }
        env.update(
            {
                key: str(value)
                for key, value in runtime.get("env", {}).items()
                if key in _SAFE_ENV
            }
        )
        env.update(
            {
                "TASK_ID": str(case["task_id"]),
                "CASE_RUN_ID": str(case["case_run_id"]),
                "SCENARIO_ID": str(case["scenario_id"]),
                "SCENARIO_URI": str(scenario_path),
                "OUTPUT_DIR": str(output_dir),
                "LOG_DIR": str(log_dir),
                "SEED": str(runtime.get("env", {}).get("SIM_SEED", case.get("seed") or 0)),
                "SIM_SEED": str(runtime.get("env", {}).get("SIM_SEED", case.get("seed") or 0)),
            }
        )
        return env

    def _result(
        self, exit_code: int, stdout: bytes, stderr: bytes, output_dir: Path
    ) -> tuple[str, int, str]:
        eval_result = output_dir / "eval_result.json"
        if eval_result.exists() and exit_code in {0, 1}:
            try:
                payload = json.loads(eval_result.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = None
            if isinstance(payload, dict):
                reason = (
                    ""
                    if payload.get("result") == "pass"
                    else str(payload.get("reason") or "metric_threshold_exceeded")
                )
                return "succeeded", 0, reason
        payload = self._parse(stdout)
        if payload is None:
            return "failed", exit_code or 1, stderr.decode("utf-8", "replace")[-400:]
        status = "succeeded" if exit_code == 0 else "failed"
        reason = str(payload.get("reason") or "")
        return status, exit_code, reason

    def _metrics(self, stdout: bytes, output_dir: Path) -> dict[str, Any]:
        result_file = output_dir / "eval_result.json"
        if result_file.exists():
            try:
                data = json.loads(result_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            if isinstance(data, dict):
                metrics: dict[str, Any] = {}
                for key, metric in (data.get("metrics") or {}).items():
                    functions = list((metric.get("functions") or {}).values())
                    metrics[key] = {
                        "value": functions[0].get("value") if functions else None,
                        "pass": metric.get("pass"),
                    }
                return metrics
        payload = self._parse(stdout)
        raw = payload.get("metrics", {}) if payload else {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _parse(stdout: bytes) -> dict[str, Any] | None:
        try:
            data = json.loads(stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _substitute(value: str, substitutions: dict[str, str]) -> str:
        for key, replacement in substitutions.items():
            value = value.replace("${" + key + "}", replacement)
        return value


def _signal_process(process: asyncio.subprocess.Process, sig: signal.Signals) -> None:
    if process.returncode is None:
        try:
            os.killpg(os.getpgid(process.pid), sig)
        except ProcessLookupError:
            return


def _work_segment(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _object_segment(value: str) -> str:
    encoded = quote(value, safe="")
    return encoded.replace(".", "%2E") if encoded in {".", ".."} else encoded


async def _main() -> None:
    settings = load_settings()
    if not settings.worker_api_url or not settings.worker_token or not settings.object_store_bucket:
        raise RuntimeError("Worker requires SIM_WORKER_API_URL, SIM_WORKER_TOKEN and S3 bucket settings")
    client = SchedulerWorkerClient(settings.worker_api_url, settings.worker_token)
    store = S3FileStore(
        settings.data_dir / "worker-cache",
        client=create_s3_client(
            endpoint_url=settings.object_store_endpoint_url,
            region=settings.object_store_region,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
        ),
        bucket=settings.object_store_bucket,
        prefix=settings.object_store_prefix,
    )
    worker = Worker(
        client=client,
        store=store,
        worker_id=os.getenv("POD_NAME") or socket.gethostname(),
        slots=int(os.getenv("SIM_WORKER_SLOTS", "1")),
        poll_sec=settings.worker_poll_sec,
        heartbeat_sec=settings.worker_heartbeat_sec,
    )
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(worker.stop()))
    loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(worker.stop()))
    mode = os.getenv("SIM_WORK_MODE", "poll")
    try:
        spec = json.loads(os.environ["SIM_WORK_SPEC"]) if mode == "single" else None
        await worker.run(spec)
    finally:
        await client.close()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(_main())
