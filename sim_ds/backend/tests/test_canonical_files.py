from pathlib import Path

import pytest
from backend.shared.canonical import canonical_json, decode_cursor, encode_cursor, sha256_json
from backend.shared.errors import AppError
from backend.shared.files import FileStore


def test_cursor_roundtrip_and_validation() -> None:
    cursor = encode_cursor("123.456", "scn_1")
    assert decode_cursor(cursor, 2) == ["123.456", "scn_1"]
    with pytest.raises(AppError) as exc:
        decode_cursor("not-base64!", 2)
    assert exc.value.code == "INVALID_CURSOR"
    with pytest.raises(AppError):
        decode_cursor(encode_cursor("1"), 2)


def test_canonical_checksum_is_stable() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert sha256_json({"b": 1, "a": 2}) == sha256_json({"a": 2, "b": 1})


def test_publish_verify_and_temp_recovery(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    published = store.publish("scenarios/s1/v1.json", {"version": 1})
    assert store.verify(published.uri, published.checksum)
    assert not store.verify(published.uri, "sha256:bad")

    target = store.resolve("scenarios/s1/v2.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.with_name(target.name + ".tmp").write_text('{"version":2}', encoding="utf-8")
    recovered = store.recover_temp("scenarios/s1/v2.json")
    assert recovered is not None
    assert recovered.checksum == sha256_json({"version": 2})


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    with pytest.raises(AppError) as exc:
        store.resolve("../outside.json")
    assert exc.value.code == "INVALID_URI"
