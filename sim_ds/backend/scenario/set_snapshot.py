"""Pure ScenarioSet snapshot builders (no database or file I/O)."""

from __future__ import annotations

from typing import Any

from backend.scenario.common import set_meta_uri, set_shard_uri, set_uri
from backend.shared.auth import Principal
from backend.shared.canonical import sha256_json
from backend.shared.errors import AppError

SHARD_SIZE = 2000


def build_snapshot(
    set_id: str,
    version: int,
    name: str,
    description: str,
    project: str,
    owner: str,
    members: list[dict[str, Any]],
    frozen: bool,
    visibility: str = "private",
) -> dict[str, Any]:
    base = {
        "set_id": set_id,
        "version": version,
        "name": name,
        "description": description,
        "frozen": frozen,
        "owner": owner,
        "project": project,
        "visibility": visibility,
        "members": members,
    }
    if len(members) <= SHARD_SIZE:
        return _unsharded(base, set_id, version, name, description, members)
    return _sharded(base, set_id, version, name, description, members)


def _unsharded(
    base: dict[str, Any], set_id: str, version: int, name: str, description: str, members: list[dict[str, Any]]
) -> dict[str, Any]:
    payload = dict(base)
    checksum = sha256_json(payload)
    payload["checksum_self"] = checksum
    return {
        "members": members,
        "snapshot_uri": set_uri(set_id, version),
        "checksum_self": checksum,
        "file_checksum": sha256_json(payload),
        "payload": payload,
        "meta_payload": payload,
        "sharded": False,
        "shards": [],
        "name": name,
        "description": description,
        "version": version,
    }


def _sharded(
    base: dict[str, Any], set_id: str, version: int, name: str, description: str, members: list[dict[str, Any]]
) -> dict[str, Any]:
    shards = _build_shards(set_id, version, members)
    meta = dict(base)
    meta.pop("members")
    meta.update(
        {
            "member_count": len(members),
            "shard_count": len(shards),
            "shards": [
                {"index": s["index"], "uri": s["uri"], "file_checksum": s["file_checksum"], "count": s["count"]}
                for s in shards
            ],
        }
    )
    meta["shards"] = [
        {"index": s["index"], "uri": s["uri"], "file_checksum": s["file_checksum"], "count": s["count"]}
        for s in shards
    ]
    checksum = sha256_json({key: value for key, value in meta.items() if key != "checksum_self"})
    meta["checksum_self"] = checksum
    return {
        "members": members,
        "snapshot_uri": set_meta_uri(set_id, version),
        "checksum_self": checksum,
        "file_checksum": sha256_json(meta),
        "payload": meta,
        "meta_payload": meta,
        "sharded": True,
        "shards": shards,
        "name": name,
        "description": description,
        "version": version,
    }


def _build_shards(set_id: str, version: int, members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    shards: list[dict[str, Any]] = []
    for index in range(0, len(members), SHARD_SIZE):
        chunk = members[index : index + SHARD_SIZE]
        payload = {
            "set_id": set_id,
            "version": version,
            "shard_index": index // SHARD_SIZE,
            "members": chunk,
        }
        shards.append(
            {
                "index": index // SHARD_SIZE,
                "uri": set_shard_uri(set_id, version, index // SHARD_SIZE),
                "payload": payload,
                "file_checksum": sha256_json(payload),
                "count": len(chunk),
            }
        )
    return shards


def check_project(principal: Principal, project: str) -> None:
    if project != principal.project and not principal.admin:
        raise AppError("FORBIDDEN", "无权在该项目创建场景集", status=403)
