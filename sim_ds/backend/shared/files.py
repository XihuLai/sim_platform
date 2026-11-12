"""Immutable, checksum-verified version files.

Publication order follows the storage contract: a pending DB intent is written
first, then a stable temporary object, then an atomic rename/immutable copy, and
finally the DB pointer is switched in a short transaction. Recovery can resume
from any of those states.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from backend.shared.canonical import canonical_json, sha256_bytes
from backend.shared.errors import AppError


@dataclass(frozen=True)
class PublishedFile:
    uri: str
    checksum: str
    size: int


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, uri: str) -> Path:
        path = Path(uri)
        if not path.is_absolute():
            path = self.root / path
        resolved = path.resolve()
        if self.root.resolve() not in resolved.parents and resolved != self.root.resolve():
            raise AppError("INVALID_URI", "文件路径越界", status=400)
        return resolved

    def relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root.resolve()))

    def read_bytes(self, path: Path) -> bytes:
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise AppError("FILE_MISSING", f"文件不存在：{path.name}", status=404) from exc

    def checksum(self, path: Path) -> str:
        return sha256_bytes(self.read_bytes(path))

    def _fsync_dir(self, directory: Path) -> None:
        try:
            fd = os.open(directory, os.O_DIRECTORY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def publish(self, relative_uri: str, payload: object) -> PublishedFile:
        """Write canonical JSON through a stable temp object and atomic rename."""
        final = self.resolve(relative_uri)
        final.parent.mkdir(parents=True, exist_ok=True)
        body = canonical_json(payload).encode("utf-8")
        checksum = sha256_bytes(body)
        tmp = final.with_name(final.name + ".tmp")
        if tmp.exists() and self.checksum(tmp) != checksum:
            tmp.unlink()
        if not tmp.exists():
            fd, name = tempfile.mkstemp(prefix=".publish-", dir=str(final.parent))
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, tmp)
        _assert_checksum(tmp, checksum)
        os.replace(tmp, final)
        self._fsync_dir(final.parent)
        return PublishedFile(uri=self.relative(final), checksum=checksum, size=len(body))

    def recover_temp(self, relative_uri: str) -> PublishedFile | None:
        """Promote a valid stable temp object left by a crash."""
        final = self.resolve(relative_uri)
        tmp = final.with_name(final.name + ".tmp")
        if not tmp.exists():
            return None
        body = self.read_bytes(tmp)
        checksum = sha256_bytes(body)
        os.replace(tmp, final)
        self._fsync_dir(final.parent)
        return PublishedFile(uri=self.relative(final), checksum=checksum, size=len(body))

    def verify(self, uri: str, expected: str) -> bool:
        path = self.resolve(uri)
        if not path.exists():
            return False
        return self.checksum(path) == expected


def _assert_checksum(path: Path, expected: str) -> None:
    actual = sha256_bytes(path.read_bytes())
    if actual != expected:
        raise AppError(
            "CHECKSUM_MISMATCH",
            "发布文件校验和不一致",
            status=409,
            detail={"expected": expected, "actual": actual},
        )
