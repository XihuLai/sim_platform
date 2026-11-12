"""Pure task-status aggregation rules (unit-testable without a database)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

TERMINAL = {"succeeded", "failed", "canceled", "timeout", "worker_lost"}
COUNT_KEYS = (
    "queued",
    "scheduled",
    "running",
    "paused",
    "succeeded",
    "failed",
    "canceled",
    "timeout",
    "worker_lost",
)


def empty_counts() -> dict[str, int]:
    return dict.fromkeys(COUNT_KEYS, 0)


def derive_task_status(
    counts: dict[str, int],
    *,
    total: int,
    expanding: bool,
    cancel_accepted: bool,
    pause_accepted: bool,
) -> str:
    if expanding:
        return "expanding"
    active = counts.get("queued", 0) + counts.get("scheduled", 0) + counts.get("running", 0) + counts.get("paused", 0)
    if active == 0:
        if cancel_accepted:
            return "canceled"
        if total > 0 and counts.get("succeeded", 0) == total:
            return "succeeded"
        return "failed"
    if pause_accepted and counts.get("scheduled", 0) == 0 and counts.get("running", 0) == 0:
        return "paused"
    if counts.get("running", 0) > 0:
        return "running"
    if counts.get("scheduled", 0) > 0:
        return "scheduled"
    if counts.get("queued", 0) > 0:
        return "queued"
    return "paused" if counts.get("paused", 0) > 0 else "failed"


def counts_from_row(row: dict[str, Any] | None) -> dict[str, int]:
    counts = empty_counts()
    if not row:
        return counts
    for key in COUNT_KEYS:
        counts[key] = int(row.get(key) or 0)
    return counts


def is_terminal(status: str) -> bool:
    return status in TERMINAL


def retry_allowed(status: str, attempt: int, retry_max: int, retry_on: Sequence[str]) -> bool:
    return status in retry_on and attempt < retry_max
