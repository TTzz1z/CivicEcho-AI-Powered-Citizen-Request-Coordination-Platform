from functools import lru_cache
from typing import BinaryIO, Protocol

from .config import get_settings


class ObjectStorage(Protocol):
    bucket: str

    def put(self, object_key: str, stream: BinaryIO, length: int, content_type: str) -> None: ...
    def open(self, object_key: str): ...
    def delete(self, object_key: str) -> None: ...


class MinioObjectStorage:
    """S3-compatible object storage adapter. Metadata never enters the object body."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str,
                 secure: bool = False, region: str | None = None):
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
        )
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket, location=region)

    def put(self, object_key: str, stream: BinaryIO, length: int, content_type: str) -> None:
        stream.seek(0)
        self._client.put_object(self.bucket, object_key, stream, length, content_type=content_type)

    def open(self, object_key: str):
        return self._client.get_object(self.bucket, object_key)

    def delete(self, object_key: str) -> None:
        self._client.remove_object(self.bucket, object_key)


@lru_cache
def get_object_storage() -> MinioObjectStorage:
    settings = get_settings()
    return MinioObjectStorage(
        settings.object_storage_endpoint,
        settings.object_storage_access_key,
        settings.object_storage_secret_key,
        settings.object_storage_bucket,
        settings.object_storage_secure,
        settings.object_storage_region,
    )
