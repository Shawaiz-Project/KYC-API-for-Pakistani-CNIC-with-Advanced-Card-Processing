"""Private, request-scoped storage for identity-document processing.

The public request ID is deliberately not used in storage paths.  A caller gets
an unguessable directory and may write one original and one processing copy per
side.  Client-provided filenames are never accepted by this module.
"""

from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final

from django.conf import settings
from PIL import Image, UnidentifiedImageError


REQUEST_DIRECTORY_RE: Final[re.Pattern[str]] = re.compile(
    r"\Akyc-[0-9a-f]{32}\Z"
)
_SIDE_NAMES: Final[frozenset[str]] = frozenset({"front", "back"})
_IMAGE_EXTENSIONS: Final[dict[str, str]] = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}
_REQUEST_MARKER_NAME: Final[str] = ".kyc-request-storage"
_REQUEST_MARKER_CONTENT: Final[bytes] = b"kyc-request-storage-v1\n"


class UnsafeStoragePathError(ValueError):
    """Raised when a configured storage path is too broad or escapes its root."""


class UnsupportedStoredImageError(ValueError):
    """Raised when bytes are not a supported, decodable image."""


@dataclass(frozen=True)
class CleanupResult:
    """Aggregate cleanup counts without exposing individual storage paths."""

    scanned: int
    expired: int
    removed: int
    skipped: int
    failed: int


def _configured_root() -> Path:
    return Path(settings.KYC_PRIVATE_STORAGE_ROOT)


def _unsafe_root_candidates() -> set[Path]:
    candidates = {Path.cwd().resolve(), Path.home().resolve()}
    for setting_name in ("BASE_DIR", "REPOSITORY_ROOT"):
        value = getattr(settings, setting_name, None)
        if value is not None:
            candidates.add(Path(value).resolve())
    return candidates


def validate_storage_root(root: Path | str, *, create: bool = False) -> Path:
    """Return a resolved private root, rejecting broad or ambiguous targets."""

    raw_root = Path(root).expanduser()
    if raw_root.exists() and raw_root.is_symlink():
        raise UnsafeStoragePathError("Private storage root must not be a symlink")

    resolved = raw_root.resolve(strict=False)
    anchor = Path(resolved.anchor).resolve()
    if (
        resolved == anchor
        or len(resolved.parts) < 3
        or resolved in _unsafe_root_candidates()
    ):
        raise UnsafeStoragePathError("Private storage root is too broad")
    if resolved.exists() and not resolved.is_dir():
        raise UnsafeStoragePathError("Private storage root is not a directory")

    if create:
        resolved.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not resolved.is_dir() or resolved.is_symlink():
            raise UnsafeStoragePathError("Private storage root is not a safe directory")
    return resolved


def _is_direct_request_directory(path: Path, root: Path) -> bool:
    if path.is_symlink() or not REQUEST_DIRECTORY_RE.fullmatch(path.name):
        return False
    try:
        if path.resolve(strict=True).parent != root:
            return False
        marker = path / _REQUEST_MARKER_NAME
        return (
            marker.is_file()
            and not marker.is_symlink()
            and marker.read_bytes() == _REQUEST_MARKER_CONTENT
        )
    except (FileNotFoundError, OSError):
        return False


def _remove_request_directory(path: Path, root: Path) -> None:
    if not _is_direct_request_directory(path, root):
        raise UnsafeStoragePathError("Refusing to remove an unsafe request directory")
    shutil.rmtree(path)


def _coerce_bytes(content: bytes | bytearray | memoryview) -> bytes:
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise TypeError("Stored image content must be bytes-like")
    return bytes(content)


def actual_image_extension(content: bytes | bytearray | memoryview) -> str:
    """Inspect image bytes and return the canonical safe file extension."""

    payload = _coerce_bytes(content)
    try:
        with Image.open(BytesIO(payload)) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UnsupportedStoredImageError(
            "Stored content is not a decodable supported image"
        ) from exc

    extension = _IMAGE_EXTENSIONS.get(image_format or "")
    if extension is None:
        raise UnsupportedStoredImageError(
            f"Stored image format is unsupported: {image_format or 'unknown'}"
        )
    return extension


def _exclusive_write(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY

    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if descriptor != -1:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


@dataclass
class RequestStorage:
    """Storage owned by one processing request."""

    root: Path
    directory: Path
    preserve_uploads: bool

    @classmethod
    def create(
        cls,
        *,
        root: Path | str | None = None,
        preserve_uploads: bool | None = None,
    ) -> "RequestStorage":
        configured_root = _configured_root() if root is None else root
        storage_root = validate_storage_root(configured_root, create=True)
        preserve = (
            bool(settings.KYC_PRESERVE_UPLOADS)
            if preserve_uploads is None
            else preserve_uploads
        )

        # mkdir(exist_ok=False) is the cross-platform exclusive reservation.
        while True:
            request_directory = storage_root / f"kyc-{uuid.uuid4().hex}"
            try:
                request_directory.mkdir(mode=0o700, exist_ok=False)
            except FileExistsError:  # practically impossible, but safely retry
                continue
            break

        try:
            _exclusive_write(
                request_directory / _REQUEST_MARKER_NAME,
                _REQUEST_MARKER_CONTENT,
            )
        except BaseException:
            request_directory.rmdir()
            raise

        return cls(storage_root, request_directory, preserve)

    def _validate_side(self, side: str) -> str:
        if side not in _SIDE_NAMES:
            raise ValueError("side must be 'front' or 'back'")
        return side

    def _child_directory(self, name: str) -> Path:
        root = validate_storage_root(self.root)
        try:
            request_directory = self.directory.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise UnsafeStoragePathError("Request storage no longer exists") from exc
        if not _is_direct_request_directory(request_directory, root):
            raise UnsafeStoragePathError("Request storage escaped its private root")

        child = request_directory / name
        try:
            child.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError:
            pass
        if child.is_symlink() or not child.is_dir():
            raise UnsafeStoragePathError("Request storage child is unsafe")
        if child.resolve(strict=True).parent != request_directory:
            raise UnsafeStoragePathError("Request storage child escaped its directory")
        return child

    def _save_image(
        self,
        collection: str,
        side: str,
        content: bytes | bytearray | memoryview,
    ) -> Path:
        safe_side = self._validate_side(side)
        payload = _coerce_bytes(content)
        extension = actual_image_extension(payload)
        destination = self._child_directory(collection) / f"{safe_side}{extension}"
        _exclusive_write(destination, payload)
        os.utime(self.directory, None)
        return destination

    def save_original(
        self, side: str, content: bytes | bytearray | memoryview
    ) -> Path:
        """Save unchanged uploaded bytes under a content-derived extension."""

        return self._save_image("originals", side, content)

    def save_processing_copy(
        self, side: str, content: bytes | bytearray | memoryview
    ) -> Path:
        """Save encoded working-image bytes away from the immutable original."""

        return self._save_image("processing", side, content)

    def discard(self) -> None:
        """Safely remove this request directory if it still exists."""

        root = validate_storage_root(self.root)
        if self.directory.exists():
            _remove_request_directory(self.directory, root)

    def close(self) -> None:
        if not self.preserve_uploads:
            self.discard()

    def __enter__(self) -> "RequestStorage":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def cleanup_expired_request_directories(
    *,
    root: Path | str | None = None,
    retention_hours: float | None = None,
    dry_run: bool = False,
    now: float | None = None,
) -> CleanupResult:
    """Remove expired generated request directories directly below the root."""

    configured_root = _configured_root() if root is None else root
    storage_root = validate_storage_root(configured_root)
    retention = (
        float(settings.KYC_RETENTION_HOURS)
        if retention_hours is None
        else float(retention_hours)
    )
    if retention < 0:
        raise ValueError("retention_hours must not be negative")
    if not storage_root.exists():
        return CleanupResult(scanned=0, expired=0, removed=0, skipped=0, failed=0)

    cutoff = (time.time() if now is None else float(now)) - retention * 3600
    scanned = expired = removed = skipped = failed = 0

    for candidate in storage_root.iterdir():
        scanned += 1
        if not _is_direct_request_directory(candidate, storage_root):
            skipped += 1
            continue
        try:
            modified_at = candidate.stat().st_mtime
        except OSError:
            failed += 1
            continue
        # Exactly-on-the-boundary directories are retained until a later run.
        if modified_at >= cutoff:
            skipped += 1
            continue

        expired += 1
        if dry_run:
            continue
        try:
            _remove_request_directory(candidate, storage_root)
        except (OSError, UnsafeStoragePathError):
            failed += 1
        else:
            removed += 1

    return CleanupResult(
        scanned=scanned,
        expired=expired,
        removed=removed,
        skipped=skipped,
        failed=failed,
    )
