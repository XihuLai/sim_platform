#!/usr/bin/env python3
"""End-to-end smoke checks against a running API instance."""

from __future__ import annotations

import argparse
import json
import time

import httpx


def check(condition: bool, message: str) -> dict[str, object]:
    if not condition:
        raise SystemExit(f"smoke failed: {message}")
    return {"ok": True, "check": message}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8099")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.base, timeout=20.0)
    report: dict[str, object] = {}

    health = client.get("/api/health")
    report["health"] = {**check(health.status_code == 200, "health"), "body": health.json()}
    scenarios = client.get("/api/scenarios", params={"page_size": 2}).json()
    report["scenario_page"] = check(len(scenarios["items"]) <= 2, "scenario cursor page")
    if scenarios.get("next_cursor"):
        second = client.get("/api/scenarios", params={"page_size": 2, "cursor": scenarios["next_cursor"]}).json()
        first_ids = {item["id"] for item in scenarios["items"]}
        second_ids = {item["id"] for item in second["items"]}
        report["scenario_no_overlap"] = check(not first_ids & second_ids, "scenario pages do not overlap")
    tasks = client.get("/api/tasks", params={"page_size": 5}).json()["items"]
    report["task_list"] = check(bool(tasks), "task list is readable")
    if tasks:
        task = tasks[0]
        summary = client.get(f"/api/tasks/{task['task_id']}/summary")
        report["summary"] = check(summary.status_code == 200, "task summary")
        report["summary_text"] = summary.json()["text"]
        cases = client.get(f"/api/tasks/{task['task_id']}/cases", params={"page_size": 5}).json()
        report["cases"] = check(bool(cases["items"]), "case cursor page")
        if cases.get("next_cursor"):
            more = client.get(
                f"/api/tasks/{task['task_id']}/cases",
                params={"page_size": 5, "cursor": cases["next_cursor"]},
            ).json()
            report["case_no_overlap"] = check(
                not ({row["case_run_id"] for row in cases["items"]} & {row["case_run_id"] for row in more["items"]}),
                "case pages do not overlap",
            )
    sources = client.get("/api/sources", params={"page_size": 5}).json()["items"]
    ready = next((item for item in sources if item["status"] == "ready"), None)
    report["source_ready"] = check(ready is not None, "playback source indexed")
    if ready:
        channel = ready["channels"][0]["name"]
        started = time.perf_counter()
        chunk = client.get(
            f"/api/sources/{ready['source_id']}/chunk",
            params={"channel": channel, "ts": 5000, "span": 2000},
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        report["playback"] = check(chunk.status_code == 200, "playback chunk read")
        report["playback_seek_ms"] = round(elapsed_ms, 1)
        report["playback_under_500ms"] = check(elapsed_ms < 500, "playback seek < 500ms")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
