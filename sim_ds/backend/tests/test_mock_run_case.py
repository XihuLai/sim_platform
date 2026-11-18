#!/usr/bin/env python3
"""模拟 Executor 调起单个 case 运行。

职责边界（见 CONTRACT.md §8.3/§8.5）：
- 本脚本是"Executor.submit 拉起引擎"那一步的模拟，不生成任何 id。
- job_id / task_id / scenario_id / scenario_version 由上游传入：
    * job_id           ← 提交 API（sim_task.task_id）
    * task_id          ← 展开阶段（case_run.case_run_id）
    * scenario_id      ← 冻结 ScenarioSet 成员
    * scenario_version ← 冻结 ScenarioSet 成员
- scenario_uri / output_dir / log_dir 由 Executor 按契约规则渲染后传入。
- **metrics 从 scenario_uri 指向的 Scenario JSON 的 metrics[] 读取**
  （事实源，见 CONTRACT.md §2.1），不通过 CLI 单独传入。
- 本脚本只负责：读场景 → 打印全部输入到 run.log → 模拟执行 →
  按 metric 生成结果 → 写 eval_result.json。

用法：
  python -m tools.mock.mock_run_case \
    --job-id job_001 --task-id task_001 \
    --scenario-id scn_001 --scenario-version 1 \
    --seed 42 --priority 0 \
    --scenario-uri file:///data/scenarios/scn_001/v1.json \
    --output-dir /tmp/sim_mock/outputs/job_001/task_001 \
    --log-dir    /tmp/sim_mock/logs/job_001/task_001 \
    --params-json '{"timeout_sec":60}'

退出码：
  0  pass
  1  fail
  2  参数/JSON 解析错误
  3  场景文件不存在或不可读
  4  场景 metrics 为空或无可执行评测函数
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

# ── 支持的评测函数（与 metric_template.function_field_name 对齐）──
FUNCTION_REGISTRY: dict[str, dict[str, Any]] = {
    "急刹": {
        "direction": "lower_better",
        "threshold": 3.0,
        "unit": "m/s^3",
        "gen": lambda r: round(r.uniform(0.0, 8.0), 3),
    },
    "车道保持": {
        "direction": "higher_better",
        "threshold": 0.95,
        "unit": "ratio",
        "gen": lambda r: round(r.uniform(0.85, 1.0), 4),
    },
    "不画龙": {
        "direction": "lower_better",
        "threshold": 0.3,
        "unit": "m",
        "gen": lambda r: round(r.uniform(0.0, 0.6), 3),
    },
    "不猛打方向盘": {
        "direction": "lower_better",
        "threshold": 10.0,
        "unit": "deg",
        "gen": lambda r: round(r.uniform(0.0, 20.0), 2),
    },
    "到达目标车道": {
        "direction": "lower_better",
        "threshold": 0.4,
        "unit": "m",
        "gen": lambda r: round(r.uniform(0.0, 1.0), 3),
    },
}


# ── 输入模型：所有 id 与渲染路径均为必填 ─────────────────
@dataclass
class CaseInput:
    job_id: str
    task_id: str
    scenario_id: str
    scenario_version: int
    scenario_uri: str
    output_dir: str
    log_dir: str
    seed: int
    binary_id: str
    priority: int
    params: dict[str, Any]
    attempt: int = 0
    worker_id: str = ""
    resource: dict[str, Any] = field(default_factory=dict)
    # metrics 由 scenario_uri 读取后填充，不在 CaseInput 构造时传入


# ── 日志器 ─────────────────────────────────────────────
class RunLogger:
    def __init__(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
        self._t0 = time.time()

    def log(self, level: str, msg: str, **kv) -> None:
        ts = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        elapsed = int((time.time() - self._t0) * 1000)
        line = f"[{ts}] [+{elapsed:>5}ms] [{level:<5}] {msg}"
        if kv:
            line += " | " + " ".join(f"{k}={v!r}" for k, v in kv.items())
        self._f.write(line + "\n")
        self._f.flush()
        print(line, file=sys.stdout)

    def close(self) -> None:
        self._f.close()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── 从 scenario_uri 读取 metrics ────────────────────────
def resolve_scenario_path(scenario_uri: str) -> Path:
    """把 file:// URI 或本地路径统一为 Path。"""
    if scenario_uri.startswith("file://"):
        p = urlparse(scenario_uri)
        return Path(url2pathname(p.path))
    return Path(scenario_uri)


def load_scenario_metrics(scenario_uri: str) -> list[dict[str, Any]]:
    """读 Scenario JSON，返回启用的 metric 列表（原始结构）。

    返回的每项形如：
      {
        "metric_def_fname": "急刹",
        "metric_def_ver": 1,
        "alias": null,
        "functions": [ {"function_field_name":"急刹","env":{...}}, ... ],
        "ret": "pass", "action": "not_stop_sim"
      }
    只保留 enabled=true 且 functions 非空的项。
    """
    path = resolve_scenario_path(scenario_uri)
    if not path.exists():
        raise FileNotFoundError(f"scenario file not found: {path}")
    with open(path, encoding="utf-8") as f:
        scenario = json.load(f)
    metrics = scenario.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("scenario.metrics is empty or not a list")

    enabled: list[dict[str, Any]] = []
    for m in metrics:
        if not m.get("enabled", True):
            continue
        # New Scenario.metrics shape: id/name/desc + functions directly.
        # Keep the old wrapper shape readable for historical versions.
        cfg = m.get("config") or {}
        funcs = m.get("functions") or cfg.get("functions") or []
        if not funcs:
            continue
        enabled.append({
            "metric_def_fname": m.get("name") or m.get("metric_def_fname") or m.get("id")
            or m.get("metric_def_id"),
            "metric_def_ver": m.get("version") or m.get("metric_def_ver"),
            "alias": m.get("alias"),
            "functions": funcs,
            "ret": m.get("ret", cfg.get("ret", "pass")),
            "action": m.get("action", cfg.get("action", "not_stop_sim")),
        })
    if not enabled:
        raise ValueError("scenario has no enabled metric with functions")
    return enabled


# ── 核心：模拟执行 ──────────────────────────────────────
def run_case(inp: CaseInput) -> dict:
    out_dir = Path(inp.output_dir)
    log_dir = Path(inp.log_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = RunLogger(log_dir / "run.log")

    # 1) 打印所有输入（metrics 在读取场景后再打印）
    logger.log("INFO", "=== CASE INPUT ===")
    logger.log("INFO", "job_id", v=inp.job_id)
    logger.log("INFO", "task_id", v=inp.task_id)
    logger.log("INFO", "scenario_id", v=inp.scenario_id)
    logger.log("INFO", "scenario_version", v=inp.scenario_version)
    logger.log("INFO", "binary_id", v=inp.binary_id)
    logger.log("INFO", "priority", v=inp.priority)
    logger.log("INFO", "attempt", v=inp.attempt)
    logger.log("INFO", "worker_id", v=inp.worker_id or "(unset)")
    logger.log("INFO", "seed", v=inp.seed)
    logger.log("INFO", "resource", v=inp.resource or {})
    logger.log("INFO", "params", v=inp.params)
    logger.log("INFO", "SCENARIO_URI", v=inp.scenario_uri)
    logger.log("INFO", "OUTPUT_DIR", v=inp.output_dir)
    logger.log("INFO", "LOG_DIR", v=inp.log_dir)

    # 2) 从场景 JSON 读取 metrics
    logger.log("INFO", "loading metrics from scenario", uri=inp.scenario_uri)
    try:
        scenario_metrics = load_scenario_metrics(inp.scenario_uri)
    except FileNotFoundError as e:
        logger.log("ERROR", "scenario file not found", error=str(e))
        logger.close()
        raise
    except ValueError as e:
        logger.log("ERROR", "scenario metrics invalid", error=str(e))
        logger.close()
        raise

    for sm in scenario_metrics:
        logger.log("INFO", "scenario metric",
                   metric_def_fname=sm["metric_def_fname"],
                   metric_def_ver=sm["metric_def_ver"],
                   alias=sm["alias"],
                   functions=[f["function_field_name"] for f in sm["functions"]])
    logger.log("INFO", "=== END INPUT ===")

    started = time.time()
    rnd = random.Random(inp.seed)

    # 3) 模拟引擎启动 + 运行
    logger.log("INFO", "engine starting", binary=inp.binary_id)
    time.sleep(rnd.uniform(0.02, 0.1))

    timeout_sec = int(inp.params.get("timeout_sec", 60))
    work_sec = max(0.05, min(timeout_sec * rnd.uniform(0.01, 0.05), 2.0))
    logger.log("INFO", "engine running", simulated_work_sec=round(work_sec, 3))
    time.sleep(work_sec)

    # 4) 按场景 metrics 的 functions 逐个评测
    logger.log("INFO", "=== METRIC EVAL START ===")
    metric_results: dict[str, dict[str, Any]] = {}
    all_pass = True

    # metric_key 用 metric_def_fname + alias 区分（同 def 多组）
    for sm in scenario_metrics:
        key = sm["metric_def_fname"]
        if sm["alias"]:
            key = f"{key}#{sm['alias']}"

        # 一个 metric 可能配多个 function（ops 组合），逐个执行
        per_func: dict[str, dict[str, Any]] = {}
        metric_pass = True
        for fn in sm["functions"]:
            fname = fn.get("function_field_name")
            spec = FUNCTION_REGISTRY.get(fname) if fname else None
            if spec is None:
                # 模板 function_field_name 与 metric 名称可能不同（如 画龙 / 不画龙），
                # 单 case 模拟脚本按 metric 名称回退到同名规则。
                spec = FUNCTION_REGISTRY.get(sm["metric_def_fname"])
            if spec is None:
                logger.log("WARN", "unknown function, skipped",
                           metric_key=key, function_field_name=fname)
                per_func[fname or "<unknown>"] = {
                    "value": None, "pass": None, "error": "unknown_function",
                }
                metric_pass = False
                continue

            value = spec["gen"](rnd)
            direction = spec["direction"]
            threshold = spec["threshold"]
            passed = value <= threshold if direction == "lower_better" else value >= threshold
            per_func[fname] = {
                "value": value,
                "pass": bool(passed),
                "unit": spec["unit"],
                "direction": direction,
                "threshold": threshold,
                "env": fn.get("env", {}),
            }
            if not passed:
                metric_pass = False
            logger.log("INFO", "function evaluated",
                       metric_key=key, function_field_name=fname,
                       value=value, threshold=threshold,
                       direction=direction, pass_=passed, unit=spec["unit"])

        # metric 级结论：functions 全 pass 才算 pass（ops 暂按 AND 处理）
        metric_results[key] = {
            "metric_def_fname": sm["metric_def_fname"],
            "metric_def_ver": sm["metric_def_ver"],
            "alias": sm["alias"],
            "ret": sm["ret"],
            "action": sm["action"],
            "pass": bool(metric_pass),
            "functions": per_func,
        }
        if not metric_pass:
            all_pass = False
    logger.log("INFO", "=== METRIC EVAL END ===")

    finished = time.time()

    # 5) 汇总结果
    result = "pass" if all_pass else "fail"
    report = {
        "job_id": inp.job_id,
        "task_id": inp.task_id,
        "scenario_id": inp.scenario_id,
        "scenario_version": inp.scenario_version,
        "binary_id": inp.binary_id,
        "priority": inp.priority,
        "attempt": inp.attempt,
        "worker_id": inp.worker_id,
        "status": "succeeded",
        "result": result,
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "duration_ms": int((finished - started) * 1000),
        "inputs": {
            "seed": inp.seed,
            "params": inp.params,
            "resource": inp.resource,
            "SCENARIO_URI": inp.scenario_uri,
            "OUTPUT_DIR": inp.output_dir,
            "LOG_DIR": inp.log_dir,
            "scenario_metrics_count": len(scenario_metrics),
        },
        "metrics": metric_results,
    }

    # 6) 写 eval_result.json
    eval_path = out_dir / "eval_result.json"
    with open(eval_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.log("INFO", "eval_result written", path=str(eval_path))

    # 7) 收尾
    logger.log("INFO", "case finished",
               result=result, duration_ms=report["duration_ms"],
               pass_cnt=sum(1 for m in metric_results.values() if m.get("pass")),
               fail_cnt=sum(1 for m in metric_results.values() if m.get("pass") is False))
    logger.close()

    return report


# ── CLI：删除 --metrics-json，其余保持 required ─────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Mock run a single case（metrics 从 scenario_uri 读取）")
    # 上游生成的 id（必填）
    ap.add_argument("--job-id", required=True,
                    help="sim_task.task_id，由提交 API 生成")
    ap.add_argument("--task-id", required=True,
                    help="case_run.case_run_id，由展开阶段生成")
    ap.add_argument("--scenario-id", required=True,
                    help="场景 id，来自冻结 ScenarioSet 成员")
    ap.add_argument("--scenario-version", type=int, required=True,
                    help="场景版本，来自冻结 ScenarioSet 成员")
    # Executor 渲染后的路径（必填）
    ap.add_argument("--scenario-uri", required=True,
                    help="Executor 渲染后的 SCENARIO_URI（指向 Scenario JSON）")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--log-dir", required=True)
    # 执行参数
    ap.add_argument("--seed", type=int, required=True,
                    help="执行种子，由调度器按 case 派生或 params.seed 传入")
    ap.add_argument("--binary-id", default="sim_engine@1.4.2")
    ap.add_argument("--priority", type=int, default=5)
    ap.add_argument("--attempt", type=int, default=0)
    ap.add_argument("--worker-id", default="")
    ap.add_argument("--params-json", default='{"timeout_sec":60}',
                    help="业务参数 JSON")
    ap.add_argument("--resource-json", default='{"cpu":2,"mem_gb":8,"gpu":0}')
    # 注意：不再有 --metrics-json
    args = ap.parse_args(argv)

    try:
        params = json.loads(args.params_json)
        resource = json.loads(args.resource_json)
    except json.JSONDecodeError as e:
        print(f"error: JSON 解析失败: {e}", file=sys.stderr)
        return 2
    if not isinstance(params, dict):
        print("error: --params-json 必须是对象", file=sys.stderr)
        return 2

    inp = CaseInput(
        job_id=args.job_id,
        task_id=args.task_id,
        scenario_id=args.scenario_id,
        scenario_version=args.scenario_version,
        scenario_uri=args.scenario_uri,
        output_dir=args.output_dir,
        log_dir=args.log_dir,
        seed=args.seed,
        binary_id=args.binary_id,
        priority=args.priority,
        params=params,
        attempt=args.attempt,
        worker_id=args.worker_id,
        resource=resource,
    )

    try:
        report = run_case(inp)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
