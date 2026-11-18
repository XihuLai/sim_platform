"""Contract shared by local and Kubernetes-backed executors."""

from __future__ import annotations

from typing import Any, Protocol


class Executor(Protocol):
    name: str
    supports_pause: bool
    dispatch_mode: str

    async def submit(self, case: dict[str, Any]) -> None: ...

    async def pause(self, case_run_id: str) -> bool: ...

    async def resume(self, case_run_id: str) -> bool: ...

    async def cancel(self, case_run_id: str) -> bool: ...

    def status(self, case_run_id: str) -> str: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...
