"""Receipt storage in MinIO (S3 API).

Receipts are streamed through the authenticated backend, so the MinIO bucket stays
private and MinIO never needs to be reachable from users' browsers.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from pathlib import Path
from functools import lru_cache
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .config import get_settings

log = logging.getLogger(__name__)


class StorageUnavailable(Exception):
    """Raised when receipt storage can't be reached or misbehaves."""


class ReceiptStorage(Protocol):
    def ensure_bucket(self) -> None: ...
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def open(self, key: str) -> Iterator[bytes]: ...
    def delete(self, key: str) -> None: ...
    def ping(self) -> bool: ...


class UnconfiguredStorage:
    """Let local expense testing run without consulting external credentials."""

    def ensure_bucket(self) -> None:
        raise StorageUnavailable("MinIO credentials are not configured")

    def put(self, key: str, data: bytes, content_type: str) -> None:
        raise StorageUnavailable("MinIO credentials are not configured")

    def open(self, key: str) -> Iterator[bytes]:
        raise StorageUnavailable("MinIO credentials are not configured")

    def delete(self, key: str) -> None:
        raise StorageUnavailable("MinIO credentials are not configured")

    def ping(self) -> bool:
        return False


class LocalReceiptStorage:
    """Receipts in a folder beside the app (desktop/SQLite testing). Keys are app-generated."""

    _KEY = re.compile(r"^[0-9]{4}/[0-9]{2}/[0-9a-f-]{36}/[0-9a-f-]{36}\.[a-z]{3,4}$")

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        if not self._KEY.match(key):
            raise StorageUnavailable("Invalid receipt key")
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise StorageUnavailable("Invalid receipt key")
        return path

    def ensure_bucket(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageUnavailable(f"Cannot create receipt folder {self.root}") from exc

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError as exc:
            log.error("Receipt write failed for key %s: %s", key, exc)
            raise StorageUnavailable("Receipt storage is unavailable") from exc

    def open(self, key: str) -> Iterator[bytes]:
        path = self._path(key)
        try:
            handle = path.open("rb")
        except OSError as exc:
            log.error("Receipt read failed for key %s: %s", key, exc)
            raise StorageUnavailable("Receipt storage is unavailable") from exc

        def chunks() -> Iterator[bytes]:
            with handle:
                while block := handle.read(64 * 1024):
                    yield block

        return chunks()

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageUnavailable("Receipt storage is unavailable") from exc

    def ping(self) -> bool:
        return self.root.is_dir() and os.access(self.root, os.W_OK)


class S3ReceiptStorage:
    def __init__(self) -> None:
        s = get_settings()
        self.bucket = s.MINIO_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=s.minio_url,
            aws_access_key_id=s.MINIO_ACCESS_KEY or None,
            aws_secret_access_key=s.MINIO_SECRET_KEY or None,
            region_name=s.MINIO_REGION,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 2},
            ),
        )

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in ("404", "NoSuchBucket", "NotFound"):
                raise StorageUnavailable(f"Cannot access bucket '{self.bucket}': {code}") from exc
            try:
                self.client.create_bucket(Bucket=self.bucket)
                log.info("Created private bucket '%s'", self.bucket)
            except (BotoCoreError, ClientError) as create_exc:
                raise StorageUnavailable(f"Cannot create bucket '{self.bucket}'") from create_exc
        except BotoCoreError as exc:
            raise StorageUnavailable("MinIO is unreachable") from exc

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        except (BotoCoreError, ClientError) as exc:
            log.error("Receipt upload failed for key %s: %s", key, exc)
            raise StorageUnavailable("Receipt storage is unavailable") from exc

    def open(self, key: str) -> Iterator[bytes]:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            log.error("Receipt download failed for key %s: %s", key, exc)
            raise StorageUnavailable("Receipt storage is unavailable") from exc
        body = obj["Body"]

        def chunks() -> Iterator[bytes]:
            try:
                while block := body.read(64 * 1024):
                    yield block
            finally:
                body.close()

        return chunks()

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            log.error("Receipt delete failed for key %s: %s", key, exc)
            raise StorageUnavailable("Receipt storage is unavailable") from exc

    def ping(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except (BotoCoreError, ClientError):
            return False


@lru_cache
def _default_storage() -> S3ReceiptStorage:
    return S3ReceiptStorage()


def get_storage() -> ReceiptStorage:
    """FastAPI dependency (overridden in tests)."""
    settings = get_settings()
    if settings.receipt_backend == "local":
        return LocalReceiptStorage(settings.receipt_path)
    if not settings.MINIO_ACCESS_KEY or not settings.MINIO_SECRET_KEY:
        return UnconfiguredStorage()
    return _default_storage()
