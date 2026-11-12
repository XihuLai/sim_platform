"""Deterministic log-resimulation engine used by the LocalExecutor.

It is intentionally dependency-free and reproducible: the same scenario, seed
and metric configuration always produce the same metric values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _uniform(*parts: object) -> float:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(0xFFFFFFFFFFFF)


def _metrics(scenario: dict[str, Any], seed: str, requested: list[str]) -> dict[str, Any]:
    keys: list[str] = list(requested)
    for item in scenario.get("metrics", []):
        if item.get("enabled", True):
            alias = item.get("alias")
            key = f"{item['metric_def_id']}@{alias}" if alias else item["metric_def_id"]
            if key not in keys:
                keys.append(key)
    if not keys:
        keys = ["default.pass_rate"]
    result: dict[str, Any] = {}
    for key in keys:
        draw = _uniform(scenario.get("scenario_id"), seed, key)
        value = round(draw * 100, 4)
        threshold = 20.0
        passed = value >= threshold
        result[key] = {"value": value, "pass": passed}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="deterministic log resimulation")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", default="0")
    parser.add_argument("--binary", default="log-resim")
    parser.add_argument("--metrics", nargs="*", default=[])
    args = parser.parse_args()
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        raise SystemExit(f"scenario missing: {scenario_path}")
    scenario: dict[str, Any] = json.loads(scenario_path.read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    metrics = _metrics(scenario, str(args.seed), list(args.metrics))
    payload = {
        "engine": args.binary,
        "scenario_id": scenario.get("scenario_id"),
        "scenario_version": scenario.get("version"),
        "seed": args.seed,
        "metrics": metrics,
        "exit_code": 0,
    }
    (out / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "sim_manifest.json").write_text(
        json.dumps(
            {
                "duration_ms": 180000,
                "channels": [
                    {"name": "camera_front", "type": "video", "fps": 15},
                    {"name": "lidar_top", "type": "pointcloud", "fps": 10},
                    {"name": "can", "type": "timeseries", "fps": 50},
                    {"name": "ego_pose", "type": "pose", "fps": 20},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
