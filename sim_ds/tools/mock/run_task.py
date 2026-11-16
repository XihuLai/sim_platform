#!/usr/bin/env python3
"""模拟跑单个 case，输出 JSON 报告。

用法：
  python -m tools.mock.mock_run_task --job-id J1 [--task-id T1] [--seed 0]
  python -m tools.mock.mock_run_task --job-id J1 --out /tmp/r.json

输出（stdout 或 --out 文件）：
{
  "job_id": "J1",
  "task_id": "T1",
  "scenario_id": "scn_xxx",
  "status": "succeeded|failed",
  "result": "pass|fail",
  "metrics": {
    "safe.collision.rate": {"value": 0.12, "pass": true},
    "comfort.jerk.p95":    {"value": 2.7,  "pass": false}
  },
  "duration_ms": 1234,
  "exit_code": 0,
  "reason": "",
  "started_at": "2026-05-12T10:00:00Z",
  "finished_at": "2026-05-12T10:00:01Z"
}
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import uuid
from datetime import datetime, timezone

# 结果分布：pass 70% / fail 30%（可按需调）
PASS_RATE = 0.7
# 引擎崩溃概率（模拟 infra 失败，result=null, status=failed）
CRASH_RATE = 0.02

# 可选 metric 池（与契约示例一致）
METRIC_POOL = [
    ("safe.collision.rate", "lower_better", 0.1),
    ("safe.ttc.min",        "higher_better", 2.0),
    ("comfort.jerk.p95",    "lower_better", 2.5),
    ("compliance.speed",    "lower_better", 5.0),
    ("efficiency.route_done","higher_better", 0.95),
]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_one_case(job_id: str, task_id: str | None, seed: int | None) -> dict:
    """执行单个 case，返回报告 dict。"""
    if task_id is None:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
    rnd = random.Random(seed) if seed is not None else random.Random()

    started = time.time()
    # 模拟执行耗时 0.05~0.5s（demo 用，生产按引擎实际）
    time.sleep(rnd.uniform(0.05, 0.5))

    scenario_id = f"scn_{uuid.uuid4().hex[:8]}"
    crashed = rnd.random() < CRASH_RATE

    if crashed:
        finished = time.time()
        return {
            "job_id": job_id,
            "task_id": task_id,
            "scenario_id": scenario_id,
            "status": "failed",
            "result": None,
            "metrics": {},
            "duration_ms": int((finished - started) * 1000),
            "exit_code": rnd.choice([1, 2, 3, 137]),  # 137=OOM kill
            "reason": rnd.choice(["engine_crash", "worker_lost", "oom"]),
            "started_at": _iso(started),
            "finished_at": _iso(finished),
        }

    # 随机选 1~3 个 metric 并生成值
    n_metrics = rnd.randint(1, 3)
    chosen = rnd.sample(METRIC_POOL, n_metrics)
    metrics: dict[str, dict] = {}
    for name, direction, threshold in chosen:
        # 生成围绕阈值的值，制造 pass/fail 混合
        if direction == "lower_better":
            value = round(rnd.uniform(0, threshold * 2), 4)
            passed = value <= threshold
        else:
            value = round(rnd.uniform(threshold * 0.5, threshold * 1.5), 4)
            passed = value >= threshold
        metrics[name] = {"value": value, "pass": bool(passed)}

    # 整体 result：全部 metric pass 才算 pass（可改为加权/关键 metric）
    overall_pass = all(m["pass"] for m in metrics.values())
    # 再叠加一次整体分布，避免"全 metric pass 比例过高"导致结果偏斜
    if rnd.random() > PASS_RATE:
        overall_pass = False

    finished = time.time()
    return {
        "job_id": job_id,
        "task_id": task_id,
        "scenario_id": scenario_id,
        "status": "succeeded",
        "result": "pass" if overall_pass else "fail",
        "metrics": metrics,
        "duration_ms": int((finished - started) * 1000),
        "exit_code": 0,
        "reason": "" if overall_pass else "metric_threshold_exceeded",
        "started_at": _iso(started),
        "finished_at": _iso(finished),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mock run a single case")
    ap.add_argument("--job-id", required=True, help="所属 job 标识")
    ap.add_argument("--task-id", default=None, help="case 标识；缺省自动生成")
    ap.add_argument("--seed", type=int, default=None, help="随机种子（可复现）")
    ap.add_argument("--out", default=None, help="输出文件路径；缺省写 stdout")
    args = ap.parse_args(argv)

    report = run_one_case(args.job_id, args.task_id, args.seed)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"written: {args.out}", file=sys.stderr)
    else:
        print(text)
    # 退出码：succeeded=0，failed=1（便于 shell 判断）
    return 0 if report["status"] == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())