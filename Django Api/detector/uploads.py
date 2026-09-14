"""Bounded, content-based validation for uploaded document images.

The byte-for-byte upload is retained on :class:`ValidatedImage`; all decoded
arrays are independent processing copies.  Filename extensions and declared
MIME types are metadata only and are never trusted to identify the format.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO

import cv2
import numpy as np
from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import status

from .errors import KYCError


SUPPORTED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
_EXIF_ORIENTATION_TAG = 274
_EXIF_ROTATION_DEGREES = {3: 180, 5: 90, 6: 90, 7: 270, 8: 270}
_MIRRORED_EXIF_ORIENTATIONS = frozenset({2, 4, 5, 7})


@dataclass(frozen=True, eq=False)
class ValidatedImage:
    """A verified upload plus an EXIF-corrected BGR processing image."""

    side: str
    original_bytes: bytes
    image: np.ndarray
    filename: str
    declared_content_type: str | None
    actual_format: str
    encoded_width: int
    encoded_height: int
    width: int
    height: int
    exif_orientation: int
    exif_transposed: bool
    exif_rotation_degrees: int
    exif_mirrored: bool

    @property
    def bgr_image(self) -> np.ndarray:
        """Alias that makes the array's channel order explicit."""

        return self.image

    def metadata(self) -> dict[str, Any]:
        """Return JSON-safe metadata without image bytes or pixel data."""

        return {
            "side": self.side,
            "filename": self.filename,
            "declared_content_type": self.declared_content_type,
            "actual_format": self.actual_format,
            "byte_size": len(self.original_bytes),
            "encoded_dimensions": {
                "width": self.encoded_width,
                "height": self.encoded_height,
            },
            "corrected_dimensions": {"width": self.width, "height": self.height},
            "exif_orientation": self.exif_orientation,
            "exif_transposed": self.exif_transposed,
            "exif_rotation_degrees": self.exif_rotation_degrees,
            "exif_mirrored": self.exif_mirrored,
        }


def _upload_error(
    code: str,
    message: str,
    http_status: int,
    side: str,
    **details: Any,
) -> KYCError:
    return KYCError(code, message, http_status, {"side": side, **details})


def _rewind(stream: BinaryIO) -> None:
    try:
        stream.seek(0)
    except (AttributeError, OSError, ValueError):
        pass


def _read_bounded(upload: BinaryIO, *, maximum: int, side: str) -> bytes:
    """Read no more than ``maximum + 1`` bytes from a file-like upload."""

    declared_size = getattr(upload, "size", None)
    if isinstance(declared_size, int) and declared_size > maximum:
        raise _upload_error(
            "upload_too_large",
            f"The {side} image exceeds the configured upload limit.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            side,
            maximum_bytes=maximum,
            declared_bytes=declared_size,
        )

    _rewind(upload)
    data = bytearray()
    exceeded_limit = False
    try:
        while len(data) <= maximum:
            remaining = maximum + 1 - len(data)
            chunk = upload.read(min(64 * 1024, remaining))
            if not chunk:
                break
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise TypeError("upload.read() returned non-byte data")
            # A custom stream may violate the read(size) contract. Never let
            # that grow our retained buffer past the sentinel byte.
            if len(chunk) > remaining:
                data.extend(memoryview(chunk)[:remaining])
                exceeded_limit = True
                break
            data.extend(chunk)
    except KYCError:
        raise
    except Exception as exc:
        raise _upload_error(
            "invalid_upload",
            f"The {side} upload could not be read.",
            status.HTTP_400_BAD_REQUEST,
            side,
            reason=type(exc).__name__,
        ) from exc
    finally:
        _rewind(upload)

    if exceeded_limit or len(data) > maximum:
        raise _upload_error(
            "upload_too_large",
            f"The {side} image exceeds the configured upload limit.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            side,
            maximum_bytes=maximum,
        )
    if not data:
        raise _upload_error(
            "empty_upload",
            f"The {side} image is empty.",
            status.HTTP_400_BAD_REQUEST,
            side,
        )
    return bytes(data)


def _check_dimensions(width: int, height: int, *, side: str) -> None:
    maximum_dimension = int(settings.KYC_MAX_IMAGE_DIMENSION)
    maximum_pixels = int(settings.KYC_MAX_IMAGE_PIXELS)
    if width <= 0 or height <= 0:
        raise _upload_error(
            "invalid_image_dimensions",
            f"The {side} image has invalid dimensions.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            side,
            width=width,
            height=height,
        )
    if width > maximum_dimension or height > maximum_dimension:
        raise _upload_error(
            "image_dimensions_exceeded",
            f"The {side} image dimensions exceed the configured limit.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            side,
            width=width,
            height=height,
            maximum_dimension=maximum_dimension,
        )
    pixels = width * height
    if pixels > maximum_pixels:
        raise _upload_error(
            "image_pixel_limit_exceeded",
            f"The {side} image contains too many pixels.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            side,
            width=width,
            height=height,
            pixels=pixels,
            maximum_pixels=maximum_pixels,
        )


def _decode_with_pillow(data: bytes, *, side: str) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as probe:
                actual_format = (probe.format or "").upper()
                encoded_width, encoded_height = probe.size
                _check_dimensions(encoded_width, encoded_height, side=side)
                if actual_format not in SUPPORTED_IMAGE_FORMATS:
                    display_format = actual_format or "unknown"
                    raise _upload_error(
                        "unsupported_image_format",
                        "Only JPEG, PNG, and WebP document images are supported.",
                        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        side,
                        detected_format=display_format,
                        supported_formats=sorted(SUPPORTED_IMAGE_FORMATS),
                    )
                probe.verify()

            with Image.open(BytesIO(data)) as decoded:
                exif_orientation = int(decoded.getexif().get(_EXIF_ORIENTATION_TAG, 1))
                corrected = ImageOps.exif_transpose(decoded)
                corrected.load()
                rgb = corrected.convert("RGB")
                width, height = rgb.size
                _check_dimensions(width, height, side=side)
                rgb_array = np.asarray(rgb, dtype=np.uint8).copy()
    except KYCError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise _upload_error(
            "image_pixel_limit_exceeded",
            f"The {side} image contains too many pixels.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            side,
        ) from exc
    except (UnidentifiedImageError, OSError, RuntimeError, SyntaxError, TypeError, ValueError) as exc:
        raise _upload_error(
            "image_decode_failed",
            f"The {side} file is not a complete, decodable image.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            side,
            decoder="pillow",
            reason=type(exc).__name__,
        ) from exc

    bgr_image = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
    return bgr_image, {
        "actual_format": actual_format.lower(),
        "encoded_width": encoded_width,
        "encoded_height": encoded_height,
        "width": width,
        "height": height,
        "exif_orientation": exif_orientation,
        "exif_transposed": exif_orientation != 1,
        "exif_rotation_degrees": _EXIF_ROTATION_DEGREES.get(exif_orientation, 0),
        "exif_mirrored": exif_orientation in _MIRRORED_EXIF_ORIENTATIONS,
    }


def _confirm_opencv_decode(data: bytes, *, side: str) -> None:
    encoded = np.frombuffer(data, dtype=np.uint8)
    flags = cv2.IMREAD_COLOR
    if hasattr(cv2, "IMREAD_IGNORE_ORIENTATION"):
        flags |= cv2.IMREAD_IGNORE_ORIENTATION
    try:
        decoded = cv2.imdecode(encoded, flags)
    except cv2.error as exc:
        raise _upload_error(
            "image_decode_failed",
            f"The {side} file could not be decoded as an image.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            side,
            decoder="opencv",
        ) from exc
    if decoded is None or decoded.size == 0 or decoded.ndim != 3:
        raise _upload_error(
            "image_decode_failed",
            f"The {side} file could not be decoded as an image.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            side,
            decoder="opencv",
        )


def validate_upload(upload: BinaryIO | None, side: str) -> ValidatedImage:
    """Validate and decode one front/back upload.

    Raises :class:`KYCError` with status 400 for a missing/invalid stream, 413
    for configured size limits, 415 for an unsupported actual format, and 422
    for corrupt or decoder-inconsistent content.
    """

    normalized_side = str(side).strip().lower()
    if normalized_side not in {"front", "back"}:
        raise KYCError(
            "invalid_document_side",
            "Document side must be either 'front' or 'back'.",
            status.HTTP_400_BAD_REQUEST,
            {"side": normalized_side or None},
        )
    if upload is None or not hasattr(upload, "read"):
        raise _upload_error(
            "missing_upload",
            f"The {normalized_side} image is required.",
            status.HTTP_400_BAD_REQUEST,
            normalized_side,
        )

    original_bytes = _read_bounded(
        upload,
        maximum=int(settings.KYC_MAX_UPLOAD_BYTES),
        side=normalized_side,
    )
    image, image_metadata = _decode_with_pillow(original_bytes, side=normalized_side)
    _confirm_opencv_decode(original_bytes, side=normalized_side)

    supplied_name = str(getattr(upload, "name", "") or f"{normalized_side}-image")
    filename = Path(supplied_name).name or f"{normalized_side}-image"
    declared_content_type = getattr(upload, "content_type", None)
    return ValidatedImage(
        side=normalized_side,
        original_bytes=original_bytes,
        image=np.ascontiguousarray(image.copy()),
        filename=filename,
        declared_content_type=str(declared_content_type) if declared_content_type else None,
        **image_metadata,
    )


__all__ = ["SUPPORTED_IMAGE_FORMATS", "ValidatedImage", "validate_upload"]
