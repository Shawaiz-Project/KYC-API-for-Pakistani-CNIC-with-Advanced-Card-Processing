"""Private object storage with filesystem and S3-compatible backends."""

from __future__ import annotations

import io
import os
import uuid
from pathlib import Path, PurePosixPath

from django.conf import settings

from .storage import UnsafeStoragePathError, validate_storage_root


class PrivateObjectStore:
    def put(self, organization_id: str, application_id: str, kind: str, content: bytes, content_type: str) -> str:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


def _safe_key(organization_id: str, application_id: str, kind: str) -> str:
    clean_kind = "".join(char for char in kind.lower() if char.isalnum() or char in "-_")
    return str(PurePosixPath("organizations", str(organization_id), "applications", str(application_id), f"{clean_kind}-{uuid.uuid4().hex}.bin"))


class FileSystemObjectStore(PrivateObjectStore):
    def __init__(self, root: Path | None = None):
        self.root = validate_storage_root(root or settings.KYC_OBJECT_STORAGE_ROOT, create=True)

    def _path(self, key: str) -> Path:
        if PurePosixPath(key).is_absolute() or ".." in PurePosixPath(key).parts:
            raise UnsafeStoragePathError("Unsafe object key")
        target = (self.root / Path(*PurePosixPath(key).parts)).resolve(strict=False)
        if os.path.commonpath((str(self.root), str(target))) != str(self.root):
            raise UnsafeStoragePathError("Object key escaped storage root")
        return target

    def put(self, organization_id: str, application_id: str, kind: str, content: bytes, content_type: str) -> str:
        key = _safe_key(organization_id, application_id, kind)
        target = self._path(key)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3ObjectStore(PrivateObjectStore):
    def __init__(self):
        if not settings.KYC_S3_BUCKET:
            raise RuntimeError("KYC_S3_BUCKET is required for the S3 backend")
        import boto3

        self.bucket = settings.KYC_S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.KYC_S3_ENDPOINT_URL,
            region_name=settings.KYC_S3_REGION,
            aws_access_key_id=settings.KYC_S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.KYC_S3_SECRET_ACCESS_KEY,
        )

    def put(self, organization_id: str, application_id: str, kind: str, content: bytes, content_type: str) -> str:
        key = _safe_key(organization_id, application_id, kind)
        extra = {"ContentType": content_type, "CacheControl": "no-store"}
        if settings.KYC_S3_SERVER_SIDE_ENCRYPTION:
            extra["ServerSideEncryption"] = settings.KYC_S3_SERVER_SIDE_ENCRYPTION
        self.client.upload_fileobj(io.BytesIO(content), self.bucket, key, ExtraArgs=extra)
        return key

    def get(self, key: str) -> bytes:
        output = io.BytesIO()
        self.client.download_fileobj(self.bucket, key, output)
        return output.getvalue()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def get_object_store() -> PrivateObjectStore:
    backend = settings.KYC_OBJECT_STORAGE_BACKEND
    if backend == "filesystem":
        return FileSystemObjectStore()
    if backend == "s3":
        return S3ObjectStore()
    raise RuntimeError("KYC_OBJECT_STORAGE_BACKEND must be filesystem or s3")
