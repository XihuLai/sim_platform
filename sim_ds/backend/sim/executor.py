"""Local executor: real subprocess isolation, timeouts and process-tree control."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

from backend.domain.models import RuntimeConfig
from backend.scenario.common import loads
from backend.shared.canonical import sha256_text
from backend.shared.config import Settings
from backend.shared.db import Database
from backend.sim.results import ResultService


class LocalExecutor:
    name = "local"
    supports_pause = True
    dispatch_mode = "push"

    def __init__(self, db: Database, results: ResultService, settings: Settings) -> None:
        self.db = db
        self.results = results
        self.settings = settings
        self.semaphore = asyncio.Semaphore(max(1, min(settings.worker_cpu, 32)))
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.tasks: set[asyncio.Task[None]] = set()

    async def submit(self, case: dict[str, Any]) -> None:
        task = asyncio.create_task(self._run(case))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def start(self) -> None:
        return

    async def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        for process in list(self.processes.values()):
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

    async def pause(self, case_run_id: str) -> bool:
        return self._signal(case_run_id, signal.SIGSTOP)

    async def resume(self, case_run_id: str) -> bool:
        return self._signal(case_run_id, signal.SIGCONT)

    async def cancel(self, case_run_id: str) -> bool:
        process = self.processes.get(case_run_id)
        if process is None:
            return False
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return False
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except TimeoutError:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        return True

    def status(self, case_run_id: str) -> str:
        process = self.processes.get(case_run_id)
        if process is None:
            return "unknown"
        if process.returncode is None:
            return "running"
        return "succeeded" if process.returncode == 0 else "failed"

    def _signal(self, case_run_id: str, sig: signal.Signals) -> bool:
        process = self.processes.get(case_run_id)
        if process is None or process.returncode is not None:
            return False
        try:
            os.killpg(os.getpgid(process.pid), sig)
            return True
        except ProcessLookupError:
            return False

    async def _run(self, case: dict[str, Any]) -> None:
        async with self.semaphore:
            try:
                await self._execute(case)
            except Exception as exc:  # executor must never crash the scheduler loop
                await self.results.report_result(
                    report_id="auto-" + sha256_text(f"{case['id']}:{case['attempt']}:crash")[7:31],
                    case_run_id=case["id"],
                    attempt=int(case["attempt"]),
                    worker_id=self.settings.worker_id,
                    status="failed",
                    metrics={},
                    exit_code=1,
                    reason=f"executor_error:{type(exc).__name__}",
                )
            finally:
                self.processes.pop(case["id"], None)

    async def _execute(self, case: dict[str, Any]) -> None:
        task = await self.db.fetch_one("SELECT * FROM sim_task WHERE id=:id", {"id": case["task_id"]})
        if task is None:
            return
        runtime = RuntimeConfig.model_validate(loads(task["runtime_config"]))
        scenario = await self.db.fetch_one(
            "SELECT file_uri FROM scenario_version WHERE scenario_id=:sid AND version=:ver",
            {"sid": case["scenario_id"], "ver": case["scenario_version"]},
        )
        if scenario is None:
            await self._report_failure(case, "scenario_version_missing")
            return
        started = await self.results.report_start(case["id"], int(case["attempt"]), self.settings.worker_id)
        if not started:
            return
        configured_output = runtime.env.get("OUTPUT_DIR")
        if configured_output:
            output_dir = Path(configured_output).expanduser()
            if not output_dir.is_absolute():
                output_dir = Path("/tmp") / output_dir
        else:
            output_dir = Path("/tmp") / case["task_id"] / case["id"]
        log_dir = self.settings.data_dir / "logs" / case["task_id"] / case["id"]
        output_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        scenario_path = str(self._scenario_path(scenario["file_uri"]))
        seed = runtime.env.get("SIM_SEED", str(self.settings.seed))
        substitutions = {
            "SCENARIO_URI": scenario_path,
            "OUTPUT_DIR": str(output_dir),
            "SEED": seed,
            "LOG_DIR": str(log_dir),
        }
        args = [self._substitute(arg, substitutions) for arg in runtime.args]
        command = self._command(case, task, args, scenario_path, output_dir, log_dir, seed)
        env = self._environment(runtime, case, scenario_path, output_dir, log_dir, seed)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(output_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self.processes[case["id"]] = process
        heartbeat = asyncio.create_task(self._heartbeat_loop(case["id"], int(case["attempt"])))
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=runtime.timeout_sec)
        except TimeoutError:
            await self._timeout(case, runtime, process, heartbeat)
            return
        heartbeat.cancel()
        await self._finish(case, process.returncode or 0, stdout, stderr, output_dir)

    async def _timeout(self, case: dict[str, Any], runtime: RuntimeConfig, process: Any, heartbeat: Any) -> None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        heartbeat.cancel()
        await self.results.report_result(
            report_id=self._report_id(case, "timeout"),
            case_run_id=case["id"],
            attempt=int(case["attempt"]),
            worker_id=self.settings.worker_id,
            status="timeout",
            metrics={},
            exit_code=-1,
            reason=f"timeout:{runtime.timeout_sec}s",
            output_uri=f"outputs/{case['task_id']}/{case['id']}",
        )

    async def _finish(
        self, case: dict[str, Any], code: int, stdout: bytes, stderr: bytes, output_dir: Path
    ) -> None:
        eval_file = output_dir / "eval_result.json"
        if eval_file.exists() and code in {0, 1}:
            try:
                result = json.loads(eval_file.read_text(encoding="utf-8"))
                metrics = {}
                for key, metric in (result.get("metrics") or {}).items():
                    functions = list((metric.get("functions") or {}).values())
                    value = functions[0].get("value") if functions else None
                    metrics[key] = {"value": value, "pass": metric.get("pass")}
                payload = {
                    "status": result.get("status", "succeeded"),
                    "result": result.get("result"),
                    "reason": "" if result.get("result") == "pass" else "metric_threshold_exceeded",
                    "metrics": metrics,
                }
                code = 0
            except (ValueError, OSError):
                payload = None
        else:
            payload = self._parse(stdout)
        status = "succeeded" if code == 0 and payload is not None else "failed"
        payload_reason = str(payload.get("reason") or "") if payload else ""
        if status == "succeeded":
            reason = payload_reason if payload and payload.get("result") == "fail" else ""
        else:
            reason = payload_reason or stderr.decode("utf-8", "replace")[-400:]
        await self.results.report_result(
            report_id=self._report_id(case, status),
            case_run_id=case["id"],
            attempt=int(case["attempt"]),
            worker_id=self.settings.worker_id,
            status=status,
            metrics=payload.get("metrics", {}) if payload else {},
            exit_code=code,
            reason=reason,
            output_uri=f"outputs/{case['task_id']}/{case['id']}",
        )

    async def _report_failure(self, case: dict[str, Any], reason: str) -> None:
        await self.results.report_result(
            report_id=self._report_id(case, "failed"),
            case_run_id=case["id"],
            attempt=int(case["attempt"]),
            worker_id=self.settings.worker_id,
            status="failed",
            metrics={},
            exit_code=1,
            reason=reason,
        )

    async def _heartbeat_loop(self, case_run_id: str, attempt: int) -> None:
        try:
            while True:
                await asyncio.sleep(10)
                await self.results.heartbeat(case_run_id, attempt, self.settings.worker_id)
        except asyncio.CancelledError:
            return

    def _command(
        self,
        case: dict[str, Any],
        task: dict[str, Any],
        args: list[str],
        scenario_path: str,
        output_dir: Path,
        log_dir: Path,
        seed: str,
    ) -> list[str]:
        runtime = loads(task["runtime_config"]) or {}
        binary = str(runtime.get("binary_id", "log-resim"))
        if binary == "mock_case":
            return [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "backend" / "tests" / "test_mock_run_case.py"),
                "--job-id", str(task["id"]),
                "--task-id", str(case["id"]),
                "--scenario-id", str(case["scenario_id"]),
                "--scenario-version", str(case["scenario_version"]),
                "--scenario-uri", scenario_path,
                "--output-dir", str(output_dir),
                "--log-dir", str(log_dir),
                "--seed", seed,
                "--priority", str(case.get("priority", 5)),
                "--attempt", str(case.get("attempt", 0)),
                "--worker-id", self.settings.worker_id,
                "--binary-id", "mock_case",
                "--params-json", json.dumps({"timeout_sec": runtime.get("timeout_sec", 60)}),
                "--resource-json", json.dumps(runtime.get("resource", {})),
            ]
        if binary == "mock":
            return [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "tools" / "mock" / "run_task.py"),
                "--job-id",
                str(task["id"]),
                "--task-id",
                output_dir.name,
                "--seed",
                self._mock_seed(seed, output_dir.name),
            ]
        if binary not in {"log-resim", "sim_engine"}:
            command = [sys.executable, binary] if binary.endswith(".py") else [binary]
            effective = args or [
                "--scenario", scenario_path, "--out", str(output_dir), "--seed", seed,
            ]
            return [*command, *effective]
        if args:
            return [sys.executable, "-m", "backend.sim.engine_cli", *args]
        return [
            sys.executable,
            "-m",
            "backend.sim.engine_cli",
            "--scenario",
            scenario_path,
            "--out",
            str(output_dir),
            "--seed",
            seed,
            "--binary",
            binary,
        ]

    def _environment(
        self,
        runtime: RuntimeConfig,
        case: dict[str, Any],
        scenario_path: str,
        output_dir: Path,
        log_dir: Path,
        seed: str,
    ) -> dict[str, str]:
        allowed = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "LANG": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
        }
        for key, value in runtime.env.items():
            if key in _SAFE_ENV:
                allowed[key] = value
        allowed.update(
            {
                "SCENARIO_URI": scenario_path,
                "OUTPUT_DIR": str(output_dir),
                "LOG_DIR": str(log_dir),
                "SEED": seed,
                "SIM_SEED": seed,
                "TASK_ID": case["task_id"],
                "CASE_RUN_ID": case["id"],
                "SCENARIO_ID": case["scenario_id"],
            }
        )
        return allowed

    def _scenario_path(self, uri: str) -> Path:
        path = Path(uri)
        if path.is_absolute():
            return path
        return self.settings.data_dir / path

    @staticmethod
    def _mock_seed(base: str, case_id: str) -> str:
        digest = sha256_text(f"{base}:{case_id}")[7:19]
        return str(int(digest, 16) % 1_000_000_000)

    def _substitute(self, arg: str, values: dict[str, str]) -> str:
        for key, value in values.items():
            arg = arg.replace("${" + key + "}", value)
        return arg

    def _report_id(self, case: dict[str, Any], status: str) -> str:
        return "rep-" + sha256_text(f"{case['id']}:{case['attempt']}:{status}")[7:31]

    def _parse(self, stdout: bytes) -> dict[str, Any] | None:
        try:
            data = json.loads(stdout.decode("utf-8"))
            return data if isinstance(data, dict) else None
        except (ValueError, UnicodeDecodeError):
            return None


_SAFE_ENV = {
    "SIM_SEED",
    "LOG_LEVEL",
    "SCENARIO_ID",
    "TASK_ID",
    "CASE_RUN_ID",
    "SIM_ENGINE",
}
