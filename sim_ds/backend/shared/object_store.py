"""S3-compatible immutable object storage used by the platform and workers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.shared.canonical import canonical_json, sha256_bytes
from backend.shared.errors import AppError
from backend.shared.files import FileStore, PublishedFile


def create_s3_client(
    *,
    endpoint_url: str | None,
    region: str | None,
    access_key: str | None,
    secret_key: str | None,
) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("S3 object storage requires the 'worker' optional dependencies") from exc
    options: dict[str, Any] = {}
    if endpoint_url:
        options["endpoint_url"] = endpoint_url
    if region:
        options["region_name"] = region
    if access_key:
        options["aws_access_key_id"] = access_key
    if secret_key:
        options["aws_secret_access_key"] = secret_key
    return boto3.client("s3", **options)


class S3FileStore(FileStore):
    """FileStore-compatible publication with S3 as the durable source of truth."""

    is_remote = True

    def __init__(
        self,
        root: Path,
        *,
        client: Any,
        bucket: str,
        prefix: str = "",
    ) -> None:
        super().__init__(root)
        if not bucket:
            raise ValueError("S3 bucket is required")
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _key(self, name: str) -> str:
        clean = name.lstrip("/")
        if not clean or ".." in Path(clean).parts:
            raise AppError("INVALID_URI", "对象存储路径无效", status=400)
        return f"{self.prefix}/{clean}" if self.prefix else clean

    def _uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def canonical_uri(self, uri: str) -> str:
        parsed = self._parse_uri(uri)
        if parsed is not None:
            return uri
        return self._uri(self._key(uri))

    def _parse_uri(self, uri: str) -> tuple[str, str] | None:
        parsed = urlparse(uri)
        if parsed.scheme != "s3":
            return None
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if bucket != self.bucket or not key or ".." in Path(key).parts:
            raise AppError("INVALID_URI", "对象存储 URI 不属于当前 Bucket", status=400)
        return bucket, key

    def resolve(self, uri: str) -> Path:
        parsed = self._parse_uri(uri)
        if parsed is None:
            path = super().resolve(uri)
            if not path.exists():
                key = self._key(uri)
                path.parent.mkdir(parents=True, exist_ok=True)
                self.client.download_file(self.bucket, key, str(path))
            return path
        bucket, key = parsed
        cache_key = hashlib.sha256(uri.encode("utf-8")).hexdigest()
        destination = self.root / ".object-cache" / cache_key
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(bucket, key, str(destination))
        return destination

    def publish(self, relative_uri: str, payload: object) -> PublishedFile:
        body = canonical_json(payload).encode("utf-8")
        checksum = sha256_bytes(body)
        key = self._key(relative_uri)
        from botocore.exceptions import ClientError

        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                Metadata={"sha256": checksum},
                IfNoneMatch="*",
            )
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") not in {409, 412}:
                raise
            existing = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            if sha256_bytes(existing) != checksum:
                raise AppError(
                    "IMMUTABLE_OBJECT_CONFLICT",
                    "同名对象已存在且内容不同",
                    status=409,
                    detail={"uri": self._uri(key)},
                ) from exc
        local = super().publish(relative_uri, payload)
        return PublishedFile(uri=self._uri(key), checksum=checksum, size=local.size)

    def recover_temp(self, uri: str) -> PublishedFile | None:
        parsed = self._parse_uri(uri)
        if parsed is None:
            key = self._key(uri)
            from botocore.exceptions import ClientError

            try:
                response = self.client.get_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                    final = FileStore.resolve(self, uri)
                    temp = final.with_name(final.name + ".tmp")
                    if not temp.exists():
                        return None
                    body = temp.read_bytes()
                    os.replace(temp, final)
                    self._fsync_dir(final.parent)
                    return self.publish(uri, json.loads(body))
                raise
            body = response["Body"].read()
            return PublishedFile(
                uri=self.canonical_uri(uri), checksum=sha256_bytes(body), size=len(body)
            )
        bucket, key = parsed
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return None
            raise
        body = response["Body"].read()
        return PublishedFile(uri=uri, checksum=sha256_bytes(body), size=len(body))

    def verify(self, uri: str, expected: str) -> bool:
        parsed = self._parse_uri(uri)
        bucket, key = parsed if parsed is not None else (self.bucket, self._key(uri))
        from botocore.exceptions import ClientError

        try:
            body = self.client.get_object(Bucket=bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            raise
        return sha256_bytes(body) == expected

    def download_to_file(self, uri: str, destination: Path, expected_checksum: str | None = None) -> str:
        parsed = self._parse_uri(uri)
        if parsed is None:
            raise AppError("INVALID_URI", "Worker 只允许从 s3:// URI 下载对象", status=400)
        bucket, key = parsed
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(bucket, key, str(destination))
        checksum = _file_checksum(destination)
        if expected_checksum and checksum != expected_checksum:
            destination.unlink(missing_ok=True)
            raise AppError(
                "CHECKSUM_MISMATCH",
                "下载对象校验和不一致",
                status=409,
                detail={"uri": uri, "expected": expected_checksum, "actual": checksum},
            )
        return checksum

    def upload_file(self, source: Path, uri: str) -> str:
        parsed = self._parse_uri(uri)
        if parsed is None:
            raise AppError("INVALID_URI", "Worker 只允许上传到 s3:// URI", status=400)
        bucket, key = parsed
        checksum = _file_checksum(source)
        self.client.upload_file(
            str(source), bucket, key, ExtraArgs={"Metadata": {"sha256": checksum}}
        )
        return checksum

    def upload_tree(self, source: Path, uri_prefix: str) -> str:
        parsed = self._parse_uri(uri_prefix.rstrip("/"))
        if parsed is None:
            raise AppError("INVALID_URI", "Worker 只允许上传到 s3:// URI", status=400)
        _, prefix = parsed
        root = source.resolve()
        for path in sorted(source.rglob("*")):
            resolved = path.resolve()
            if path.is_file() and resolved.is_relative_to(root):
                relative = path.relative_to(source).as_posix()
                self.upload_file(path, self._uri(f"{prefix}/{relative}"))
        return self._uri(prefix) + "/"


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
