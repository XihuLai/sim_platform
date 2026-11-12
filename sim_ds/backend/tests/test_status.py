from backend.sim.status import derive_task_status, empty_counts, retry_allowed


def counts(**values: int) -> dict[str, int]:
    result = empty_counts()
    result.update(values)
    return result


def test_queued_and_running() -> None:
    assert derive_task_status(counts(queued=3), total=3, expanding=False, cancel_accepted=False, pause_accepted=False) == "queued"
    assert derive_task_status(counts(scheduled=1, running=2), total=3, expanding=False, cancel_accepted=False, pause_accepted=False) == "running"


def test_expanding_takes_precedence() -> None:
    status = derive_task_status(counts(queued=1), total=1, expanding=True, cancel_accepted=False, pause_accepted=False)
    assert status == "expanding"


def test_terminal_states() -> None:
    assert derive_task_status(counts(succeeded=4), total=4, expanding=False, cancel_accepted=False, pause_accepted=False) == "succeeded"
    assert derive_task_status(counts(failed=1, succeeded=3), total=4, expanding=False, cancel_accepted=False, pause_accepted=False) == "failed"
    assert derive_task_status(counts(canceled=4), total=4, expanding=False, cancel_accepted=True, pause_accepted=False) == "canceled"


def test_pause_and_retry_rules() -> None:
    paused = derive_task_status(counts(paused=2), total=2, expanding=False, cancel_accepted=False, pause_accepted=True)
    assert paused == "paused"
    assert retry_allowed("timeout", 0, 1, ["timeout"]) is True
    assert retry_allowed("timeout", 1, 1, ["timeout"]) is False
    assert retry_allowed("failed", 0, 3, ["timeout"]) is False
