from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache
from threading import Lock
from typing import BinaryIO, Protocol

from urllib3 import PoolManager, Timeout

from .config import get_settings


class ObjectStorage(Protocol):
    bucket: str

    def put(self, object_key: str, stream: BinaryIO, length: int, content_type: str) -> None: ...
    def open(self, object_key: str): ...
    def delete(self, object_key: str) -> None: ...
    def size(self, object_key: str) -> int: ...


class MinioObjectStorage:
    """S3-compatible object storage adapter. Metadata never enters the object body."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str,
                 secure: bool = False, region: str | None = None, timeout_seconds: int = 5):
        try:
            from minio import Minio
        except ImportError as exc:  # pragma: no cover - deployment dependency guard
            raise RuntimeError("minio dependency is not installed") from exc
        self.bucket = bucket
        self._client = Minio(
            endpoint.removeprefix("https://").removeprefix("http://"),
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
            http_client=PoolManager(timeout=Timeout(connect=timeout_seconds, read=timeout_seconds),
                                    retries=False),
        )
        self._region = region
        self._bucket_ready = False
        self._bucket_lock = Lock()

    def bucket_exists(self) -> bool:
        return self._client.bucket_exists(self.bucket)

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        from minio.error import S3Error

        with self._bucket_lock:
            if self._bucket_ready:
                return
            if not self.bucket_exists():
                try:
                    self._client.make_bucket(self.bucket, location=self._region)
                except S3Error as exc:
                    if exc.code != "BucketAlreadyOwnedByYou":
                        raise
            self._bucket_ready = True

    def put(self, object_key: str, stream: BinaryIO, length: int, content_type: str) -> None:
        self._ensure_bucket()
        stream.seek(0)
        self._client.put_object(self.bucket, object_key, stream, length, content_type=content_type)

    def open(self, object_key: str):
        return self._client.get_object(self.bucket, object_key)

    def delete(self, object_key: str) -> None:
        self._client.remove_object(self.bucket, object_key)

    def size(self, object_key: str) -> int:
        return self._client.stat_object(self.bucket, object_key).size

    def iter_object_entries(self, prefix: str, start_after: str | None = None) -> Iterator[tuple[str, datetime | None]]:
        from minio.error import S3Error

        try:
            for item in self._client.list_objects(self.bucket, prefix=prefix, recursive=True, start_after=start_after):
                yield item.object_name, item.last_modified
        except S3Error as exc:
            if exc.code != "NoSuchBucket":
                raise


def _build_minio_storage(bucket: str) -> MinioObjectStorage:
    settings = get_settings()
    return MinioObjectStorage(
        settings.object_storage_endpoint,
        settings.object_storage_access_key,
        settings.object_storage_secret_key,
        bucket,
        settings.object_storage_secure,
        settings.object_storage_region or None,
        settings.object_storage_timeout_seconds,
    )


@lru_cache
def get_object_storage() -> MinioObjectStorage:
    """Attachment bucket storage (default OBJECT_STORAGE_BUCKET)."""
    settings = get_settings()
    return _build_minio_storage(settings.object_storage_bucket)


@lru_cache
def get_kb_object_storage() -> MinioObjectStorage:
    """Knowledge-base upload bucket (KB_UPLOAD_BUCKET). Shares MinIO credentials."""
    settings = get_settings()
    return _build_minio_storage(settings.kb_upload_bucket)


def reset_object_storage_for_tests() -> None:
    """Clear cached MinIO clients. For tests only."""
    get_object_storage.cache_clear()
    get_kb_object_storage.cache_clear()
