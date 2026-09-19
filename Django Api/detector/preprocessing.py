"""Deterministic OpenCV preprocessing and capture-quality gates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from django.conf import settings
from rest_framework import status

from .errors import KYCError
from .uploads import ValidatedImage


_MIN_CARD_ASPECT_RATIO = 1.15
_MAX_CARD_ASPECT_RATIO = 2.40


@dataclass(frozen=True)
class CardDetection:
    status: str
    count: int
    source: str
    corners: tuple[tuple[float, float], ...]
    area_ratio: float
    complete: bool
    model_detection_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "count": self.count,
            "source": self.source,
            "corners": [[round(x, 2), round(y, 2)] for x, y in self.corners],
            "area_ratio": round(self.area_ratio, 6),
            "complete": self.complete,
            "model_detection_count": self.model_detection_count,
        }


@dataclass(frozen=True)
class QualityFinding:
    check: str
    status: str
    value: Any
    threshold: Any
    message: str
    recapture_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "check": self.check,
            "status": self.status,
            "value": self.value,
            "threshold": self.threshold,
            "message": self.message,
        }
        if self.recapture_reason:
            result["recapture_reason"] = self.recapture_reason
        return result


@dataclass(frozen=True, eq=False)
class PreprocessingResult:
    corrected_image: np.ndarray
    detection: CardDetection
    quality_findings: tuple[QualityFinding, ...]
    recapture_reasons: tuple[str, ...]
    orientation_degrees: int
    card_rotation_degrees: int
    side_signal: str
    expected_side: str

    @property
    def quality_passed(self) -> bool:
        return not self.recapture_reasons

    def metadata(self) -> dict[str, Any]:
        """Return the JSON-safe portion of the preprocessing result."""

        height, width = self.corrected_image.shape[:2]
        return {
            "expected_side": self.expected_side,
            "side_signal": self.side_signal,
            "orientation_degrees": self.orientation_degrees,
            "card_rotation_degrees": self.card_rotation_degrees,
            "corrected_dimensions": {"width": width, "height": height},
            "detection": self.detection.as_dict(),
            "quality_findings": [finding.as_dict() for finding in self.quality_findings],
            "quality_passed": self.quality_passed,
            "recapture_reasons": list(self.recapture_reasons),
        }


@dataclass(frozen=True, eq=False)
class _ContourCandidate:
    corners: np.ndarray
    area_ratio: float
    touches_frame: bool


def order_quadrilateral(points: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
    """Order four points as top-left, top-right, bottom-right, bottom-left."""

    array = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    if array.shape != (4, 2) or not np.isfinite(array).all():
        raise ValueError("A quadrilateral must contain four finite (x, y) points.")
    if len(np.unique(array, axis=0)) != 4:
        raise ValueError("Quadrilateral points must be distinct.")

    center = array.mean(axis=0)
    angles = np.arctan2(array[:, 1] - center[1], array[:, 0] - center[0])
    ordered = array[np.argsort(angles)]
    start = int(np.argmin(ordered.sum(axis=1)))
    ordered = np.roll(ordered, -start, axis=0)

    # In image coordinates (positive y points down), TL->TR->BR has a
    # positive cross product. Keep TL fixed if the input winding is reversed.
    first_edge = ordered[1] - ordered[0]
    second_edge = ordered[2] - ordered[1]
    cross = float(first_edge[0] * second_edge[1] - first_edge[1] * second_edge[0])
    if cross < 0:
        ordered = ordered[[0, 3, 2, 1]]
    return np.ascontiguousarray(ordered, dtype=np.float32)


def _quad_dimensions(corners: np.ndarray) -> tuple[float, float]:
    top_left, top_right, bottom_right, bottom_left = corners
    width = max(
        float(np.linalg.norm(top_right - top_left)),
        float(np.linalg.norm(bottom_right - bottom_left)),
    )
    height = max(
        float(np.linalg.norm(bottom_left - top_left)),
        float(np.linalg.norm(bottom_right - top_right)),
    )
    return width, height


def _plausible_card_shape(corners: np.ndarray) -> bool:
    width, height = _quad_dimensions(corners)
    shorter = min(width, height)
    if shorter < 8:
        return False
    ratio = max(width, height) / shorter
    return _MIN_CARD_ASPECT_RATIO <= ratio <= _MAX_CARD_ASPECT_RATIO


def _touches_frame(corners: np.ndarray, *, width: int, height: int) -> bool:
    margin = max(2.0, min(width, height) * 0.005)
    xs = corners[:, 0]
    ys = corners[:, 1]
    return bool(
        np.any(xs <= margin)
        or np.any(ys <= margin)
        or np.any(xs >= width - 1 - margin)
        or np.any(ys >= height - 1 - margin)
    )


def _contour_candidates(image: np.ndarray) -> tuple[list[_ContourCandidate], int]:
    height, width = image.shape[:2]
    image_area = float(height * width)
    minimum_area = image_area * float(settings.KYC_MIN_CARD_AREA_RATIO)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 140, L2gradient=True)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    edges = cv2.dilate(edges, kernel, iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[_ContourCandidate] = []
    incomplete_hints = 0
    for contour in contours:
        area = float(abs(cv2.contourArea(contour)))
        bounding_x, bounding_y, bounding_width, bounding_height = cv2.boundingRect(contour)
        bounding_touches_frame = (
            bounding_x <= 2
            or bounding_y <= 2
            or bounding_x + bounding_width >= width - 2
            or bounding_y + bounding_height >= height - 2
        )
        bounding_area = float(bounding_width * bounding_height)
        if area < minimum_area:
            # A clipped card often produces an open edge contour whose enclosed
            # contour area is small even though its visible bounding rectangle
            # is card-sized. Preserve that as an incomplete-card signal.
            shorter = min(bounding_width, bounding_height)
            bounding_ratio = max(bounding_width, bounding_height) / max(shorter, 1)
            if (
                bounding_touches_frame
                and bounding_area >= minimum_area
                and _MIN_CARD_ASPECT_RATIO <= bounding_ratio <= _MAX_CARD_ASPECT_RATIO
            ):
                incomplete_hints += 1
            continue
        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0:
            continue
        approximation = cv2.approxPolyDP(contour, 0.025 * perimeter, True)

        if len(approximation) != 4 or not cv2.isContourConvex(approximation):
            if bounding_touches_frame:
                rect = cv2.minAreaRect(contour)
                box = order_quadrilateral(cv2.boxPoints(rect))
                if _plausible_card_shape(box):
                    incomplete_hints += 1
            continue

        corners = order_quadrilateral(approximation.reshape(4, 2))
        if not _plausible_card_shape(corners):
            if bounding_touches_frame:
                incomplete_hints += 1
            continue
        quad_area = float(abs(cv2.contourArea(corners)))
        candidate = _ContourCandidate(
            corners=corners,
            area_ratio=quad_area / image_area,
            touches_frame=_touches_frame(corners, width=width, height=height),
        )
        candidates.append(candidate)

    candidates.sort(key=lambda candidate: candidate.area_ratio, reverse=True)
    return candidates, incomplete_hints


def detect_card_contours(image: np.ndarray) -> tuple[CardDetection, np.ndarray]:
    """Find exactly one complete card-like quadrilateral in ``image``."""

    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3 or image.size == 0:
        raise KYCError(
            "invalid_image_array",
            "The decoded document image is invalid.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"recapture_reasons": ["image_decode_failed"]},
        )

    candidates, incomplete_hints = _contour_candidates(image)
    card_signals = len(candidates) + incomplete_hints
    if card_signals > 1:
        raise KYCError(
            "multiple_cards_detected",
            "More than one card is visible. Capture one complete card only.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {
                "card_count": card_signals,
                "recapture_reasons": ["multiple_cards"],
            },
        )
    if not candidates:
        if incomplete_hints:
            raise KYCError(
                "incomplete_card",
                "The card is cut off by the image boundary.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                {
                    "card_count": 1,
                    "recapture_reasons": ["card_outside_frame"],
                },
            )
        raise KYCError(
            "card_not_found",
            "No complete card boundary was detected.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"card_count": 0, "recapture_reasons": ["card_not_detected"]},
        )

    candidate = candidates[0]
    if candidate.touches_frame:
        raise KYCError(
            "incomplete_card",
            "The card is cut off by the image boundary.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"card_count": 1, "recapture_reasons": ["card_outside_frame"]},
        )

    corners_tuple = tuple((float(x), float(y)) for x, y in candidate.corners)
    detection = CardDetection(
        status="single_card",
        count=1,
        source="opencv_contour",
        corners=corners_tuple,
        area_ratio=candidate.area_ratio,
        complete=True,
        model_detection_count=0,
    )
    return detection, candidate.corners.copy()


def perspective_correct(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Warp an ordered card quadrilateral into a rectangular processing copy."""

    ordered = order_quadrilateral(corners)
    width_float, height_float = _quad_dimensions(ordered)
    output_width = int(round(width_float))
    output_height = int(round(height_float))
    if output_width < 2 or output_height < 2:
        raise KYCError(
            "incomplete_card",
            "The detected card boundary cannot be perspective-corrected.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"recapture_reasons": ["card_outside_frame"]},
        )

    destination = np.array(
        [
            [0, 0],
            [output_width - 1, 0],
            [output_width - 1, output_height - 1],
            [0, output_height - 1],
        ],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(ordered, destination)
    corrected = cv2.warpPerspective(
        image.copy(),
        transform,
        (output_width, output_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    if corrected is None or corrected.size == 0:
        raise KYCError(
            "perspective_correction_failed",
            "The card boundary could not be perspective-corrected.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"recapture_reasons": ["card_boundary_uncertain"]},
        )
    return np.ascontiguousarray(corrected)


def _quality_finding(
    check: str,
    passed: bool,
    value: Any,
    threshold: Any,
    pass_message: str,
    fail_message: str,
    recapture_reason: str,
) -> QualityFinding:
    return QualityFinding(
        check=check,
        status="pass" if passed else "fail",
        value=value,
        threshold=threshold,
        message=pass_message if passed else fail_message,
        recapture_reason=None if passed else recapture_reason,
    )


def assess_quality(card_image: np.ndarray) -> tuple[QualityFinding, ...]:
    """Run deterministic blur, exposure, glare, and resolution checks."""

    gray = cv2.cvtColor(card_image, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    blur_threshold = float(settings.KYC_BLUR_THRESHOLD)
    blur = _quality_finding(
        "blur",
        blur_score >= blur_threshold,
        round(blur_score, 3),
        {"minimum_laplacian_variance": blur_threshold},
        "The card has sufficient edge detail.",
        "The card image is too blurry for reliable OCR.",
        "image_blurry",
    )

    mean_luminance = float(gray.mean())
    dark_threshold = float(settings.KYC_DARK_MEAN_THRESHOLD)
    bright_threshold = float(settings.KYC_BRIGHT_MEAN_THRESHOLD)
    exposure_passed = dark_threshold <= mean_luminance <= bright_threshold
    if mean_luminance < dark_threshold:
        exposure_failure = "The card image is too dark."
        exposure_reason = "image_too_dark"
    elif mean_luminance > bright_threshold:
        exposure_failure = "The card image is too bright."
        exposure_reason = "image_too_bright"
    else:
        exposure_failure = "The card exposure is outside the supported range."
        exposure_reason = "invalid_exposure"
    exposure = _quality_finding(
        "exposure",
        exposure_passed,
        round(mean_luminance, 3),
        {"minimum_mean_luminance": dark_threshold, "maximum_mean_luminance": bright_threshold},
        "The card exposure is within the supported range.",
        exposure_failure,
        exposure_reason,
    )

    hsv = cv2.cvtColor(card_image, cv2.COLOR_BGR2HSV)
    glare_mask = (hsv[:, :, 2] >= 250) & (hsv[:, :, 1] <= 35)
    glare_ratio = float(np.count_nonzero(glare_mask) / glare_mask.size)
    glare_threshold = float(settings.KYC_GLARE_RATIO_THRESHOLD)
    glare = _quality_finding(
        "glare",
        glare_ratio <= glare_threshold,
        round(glare_ratio, 6),
        {"maximum_clipped_low_saturation_ratio": glare_threshold},
        "No excessive clipped glare was detected.",
        "Excessive glare obscures part of the card.",
        "excessive_glare",
    )

    height, width = card_image.shape[:2]
    minimum_width = int(settings.KYC_MIN_CARD_WIDTH)
    minimum_height = int(settings.KYC_MIN_CARD_HEIGHT)
    resolution_passed = width >= minimum_width and height >= minimum_height
    resolution = _quality_finding(
        "minimum_resolution",
        resolution_passed,
        {"width": width, "height": height},
        {"minimum_width": minimum_width, "minimum_height": minimum_height},
        "The corrected card resolution is sufficient.",
        "The card occupies too few pixels for reliable OCR.",
        "card_resolution_too_low",
    )
    return blur, exposure, glare, resolution


def _normalize_model_detections(model_detections: Any) -> tuple[Any, ...]:
    if model_detections is None:
        return ()
    if isinstance(model_detections, (str, bytes, Mapping)):
        return (model_detections,)
    if isinstance(model_detections, Iterable):
        return tuple(model_detections)
    return (model_detections,)


def _detection_label(detection: Any) -> str:
    if isinstance(detection, str):
        return detection
    keys = ("side", "detected_side", "label", "class_name", "class_label")
    if isinstance(detection, Mapping):
        for key in keys:
            value = detection.get(key)
            if value is not None:
                return str(value)
        return ""
    for key in keys:
        value = getattr(detection, key, None)
        if value is not None:
            return str(value)
    return ""


def _side_signal(model_detections: Sequence[Any]) -> str:
    sides: set[str] = set()
    for detection in model_detections:
        label = _detection_label(detection).strip().lower()
        if "front" in label:
            sides.add("front")
        if "back" in label or "rear" in label:
            sides.add("back")
    if len(sides) == 1:
        return next(iter(sides))
    if len(sides) > 1:
        return "uncertain"
    return "unknown"


def _yolo_crop_card(image: np.ndarray, yolo_detections: list[dict]) -> np.ndarray | None:
    """Crop the image to the highest-confidence YOLO bounding box if it is large enough."""
    if not yolo_detections:
        return None
    best = max(yolo_detections, key=lambda d: d.get("score", 0.0))
    bbox = best.get("bbox")
    if not bbox or len(bbox) < 4:
        return None
    h, w = image.shape[:2]
    x1, y1, x2, y2 = (int(round(v)) for v in bbox[:4])
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 40 or y2 - y1 < 40:
        return None
    # Require the crop to cover at least 10% of the image area
    if (x2 - x1) * (y2 - y1) < 0.10 * w * h:
        return None
    return np.ascontiguousarray(image[y1:y2, x1:x2])


def preprocess_document(
    validated: ValidatedImage,
    expected_side: str,
    model_detections: Any = None,
) -> PreprocessingResult:
    """Detect, rectify, orient, and quality-check one validated CNIC image.

    When a YOLO card detector is configured (KYC_CARD_DETECTOR_MODEL), its
    bounding-box crop is used to isolate the card before the contour pipeline
    runs, which gives significantly better results on complex backgrounds and
    partial captures.  Falls back silently to contour-only mode when YOLO is
    not loaded or produces no useful detection.

    ``model_detections`` is the optional side-label list returned by the legacy
    v1 pipeline; card geometry now comes from the YOLO/contour pipeline.
    """

    normalized_side = str(expected_side).strip().lower()
    if normalized_side not in {"front", "back"}:
        raise KYCError(
            "invalid_document_side",
            "Expected document side must be either 'front' or 'back'.",
            status.HTTP_400_BAD_REQUEST,
            {"side": normalized_side or None},
        )
    if not isinstance(validated, ValidatedImage):
        raise KYCError(
            "invalid_validated_image",
            "Preprocessing requires a validated document image.",
            status.HTTP_400_BAD_REQUEST,
            {"side": normalized_side},
        )
    if validated.side != normalized_side:
        raise KYCError(
            "invalid_document_side",
            "The validated upload slot does not match the expected side.",
            status.HTTP_400_BAD_REQUEST,
            {"validated_side": validated.side, "expected_side": normalized_side},
        )

    detections = _normalize_model_detections(model_detections)
    side_signal = _side_signal(detections)
    source = np.ascontiguousarray(validated.image.copy())

    # --- YOLO-assisted card isolation ----------------------------------------
    # Try to load the YOLO detector.  A missing/unconfigured model is not an
    # error here — we simply fall back to the full-image contour pipeline.
    yolo_crop: np.ndarray | None = None
    yolo_detection_count = 0
    try:
        from .model_registry import get_model_registry
        registry = get_model_registry()
        yolo = registry.get_card_detector()
        if yolo is not None:
            raw_detections = yolo.detect(source)
            yolo_detection_count = len(raw_detections)
            yolo_crop = _yolo_crop_card(source, raw_detections)
    except Exception:  # noqa: BLE001 — never let detector errors break uploads
        pass
    # -------------------------------------------------------------------------
    # Run contour detection on the YOLO crop when available; fall back to the
    # full source image.  If YOLO found a crop but contour detection on the
    # crop also fails, re-raise so the caller gets a meaningful error.
    detection_source_image = yolo_crop if yolo_crop is not None else source
    detection_source_label = "yolo_crop_then_contour" if yolo_crop is not None else "opencv_contour"

    contour_detection, crop_corners = detect_card_contours(detection_source_image)

    # Map crop-relative corners back to the full source image coordinate space
    # so that perspective_correct operates on the original full resolution.
    if yolo_crop is not None:
        # Recover the crop offset from the YOLO detection (best bbox)
        try:
            from .model_registry import get_model_registry as _reg
            _yolo_raw = _reg().get_card_detector()
            if _yolo_raw is not None:
                # We already have the best bbox stored; re-derive the offset
                _raw = _yolo_raw.detect(source)
                if _raw:
                    _best = max(_raw, key=lambda d: d.get("score", 0.0))
                    _bbox = _best.get("bbox", [0, 0, 0, 0])
                    h_src, w_src = source.shape[:2]
                    ox = max(0, int(round(_bbox[0])))
                    oy = max(0, int(round(_bbox[1])))
                    crop_corners[:, 0] += ox
                    crop_corners[:, 1] += oy
        except Exception:  # noqa: BLE001
            pass  # Use crop_corners as-is; perspective correction may be imperfect

    corners = crop_corners
    detection = CardDetection(
        status=contour_detection.status,
        count=contour_detection.count,
        source=detection_source_label,
        corners=contour_detection.corners,
        area_ratio=contour_detection.area_ratio,
        complete=contour_detection.complete,
        model_detection_count=len(detections) if detections else yolo_detection_count,
    )

    if side_signal in {"front", "back"} and side_signal != normalized_side:
        raise KYCError(
            "wrong_document_side",
            f"The {normalized_side} upload appears to contain the {side_signal} side.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {
                "expected_side": normalized_side,
                "side_signal": side_signal,
                "detection": detection.as_dict(),
                "recapture_reasons": ["wrong_side"],
            },
        )

    corrected = perspective_correct(source, corners)
    card_rotation_degrees = 0
    if corrected.shape[0] > corrected.shape[1]:
        corrected = cv2.rotate(corrected, cv2.ROTATE_90_CLOCKWISE)
        card_rotation_degrees = 90
    corrected = np.ascontiguousarray(corrected.copy())

    findings = assess_quality(corrected)
    recapture_reasons = tuple(
        finding.recapture_reason
        for finding in findings
        if finding.status == "fail" and finding.recapture_reason is not None
    )
    orientation_degrees = (validated.exif_rotation_degrees + card_rotation_degrees) % 360
    result = PreprocessingResult(
        corrected_image=corrected,
        detection=detection,
        quality_findings=findings,
        recapture_reasons=recapture_reasons,
        orientation_degrees=orientation_degrees,
        card_rotation_degrees=card_rotation_degrees,
        side_signal=side_signal,
        expected_side=normalized_side,
    )
    if bool(settings.KYC_QUALITY_GATES_ENABLED) and recapture_reasons:
        raise KYCError(
            "image_quality_insufficient",
            f"The {normalized_side} image does not meet capture-quality requirements.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            result.metadata(),
        )
    return result


__all__ = [
    "CardDetection",
    "PreprocessingResult",
    "QualityFinding",
    "assess_quality",
    "detect_card_contours",
    "order_quadrilateral",
    "perspective_correct",
    "preprocess_document",
]
