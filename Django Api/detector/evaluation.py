"""Privacy-preserving, grouped evaluation for the Phase 1 KYC pipeline.

The harness reports only aggregate measurements.  It never copies image paths,
group identifiers, field truth, OCR text, or predictions into its report.

Manifest schema (version 1.0)::

    {
      "schema_version": "1.0",
      "dataset": {"name": "...", "version": "..."},
      "detection_iou_threshold": 0.5,
      "pairs": [{
        "person_group_id": "opaque-person-token",
        "document_group_id": "opaque-document-token",
        "split": "held_out",
        "front_path": "/private/path/front.jpg",
        "back_path": "/private/path/back.jpg",
        "expected": {
          "fields": {"name": "canonical truth or null"},
          "urdu_text": {"front": "logical-order truth or null"},
          "card_boxes": {"front": [[x1, y1, x2, y2]]}
        }
      }]
    }

All records sharing either group identifier must have exactly one split.
Detection IoU uses axis-aligned envelopes in source-image pixel coordinates.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import platform
import re
import statistics
import time
import unicodedata
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from .errors import KYCError


FIELD_NAMES: Final[tuple[str, ...]] = (
    "name",
    "guardian_name",
    "gender",
    "country_of_stay",
    "cnic_number",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
)
SIDES: Final[tuple[str, str]] = ("front", "back")
ALLOWED_SPLITS: Final[frozenset[str]] = frozenset(
    {"train", "validation", "held_out"}
)
_OPAQUE_GROUP_RE: Final[re.Pattern[str]] = re.compile(
    r"\A[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}\Z"
)
_CNIC_LIKE_RE: Final[re.Pattern[str]] = re.compile(
    r"\A\d{5}-?\d{7}-?\d\Z"
)
_URDU_RE: Final[re.Pattern[str]] = re.compile(
    r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]"
)
_AUTO_RSS: Final[object] = object()


class ManifestValidationError(ValueError):
    """A safe, machine-readable manifest failure."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, repr=False)
class EvaluationPair:
    index: int
    split: str
    front_path: Path
    back_path: Path
    expected_fields: Mapping[str, str | None]
    expected_urdu: Mapping[str, str | None]
    expected_boxes: Mapping[str, tuple[tuple[float, float, float, float], ...]]


@dataclass(frozen=True, repr=False)
class EvaluationManifest:
    path: Path
    sha256: str
    dataset_metadata: Mapping[str, str]
    detection_iou_threshold: float
    pairs: tuple[EvaluationPair, ...]


def _manifest_error(
    code: str,
    message: str,
    *,
    pair_index: int | None = None,
) -> ManifestValidationError:
    details = {} if pair_index is None else {"pair_index": pair_index}
    return ManifestValidationError(code, message, details)


def _validate_group_id(value: Any, name: str, pair_index: int) -> str:
    if not isinstance(value, str) or not _OPAQUE_GROUP_RE.fullmatch(value):
        raise _manifest_error(
            f"invalid_{name}",
            f"{name} must be an opaque 8-128 character token.",
            pair_index=pair_index,
        )
    if value.isdigit() or _CNIC_LIKE_RE.fullmatch(value):
        raise _manifest_error(
            f"non_opaque_{name}",
            f"{name} must not contain a raw identity number.",
            pair_index=pair_index,
        )
    return value


def _as_finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _geometry_to_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, Mapping):
        for key in ("bbox", "box", "corners", "polygon"):
            if key in value:
                return _geometry_to_bbox(value[key])
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None

    if len(value) == 4 and all(_as_finite_number(item) is not None for item in value):
        x1, y1, x2, y2 = (float(item) for item in value)
    elif len(value) >= 3 and all(
        isinstance(point, Sequence)
        and not isinstance(point, (str, bytes, bytearray))
        and len(point) == 2
        and _as_finite_number(point[0]) is not None
        and _as_finite_number(point[1]) is not None
        for point in value
    ):
        xs = [float(point[0]) for point in value]
        ys = [float(point[1]) for point in value]
        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    else:
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _parse_box_collection(
    value: Any,
    *,
    pair_index: int,
    side: str,
) -> tuple[tuple[float, float, float, float], ...]:
    if value is None:
        return ()
    single = _geometry_to_bbox(value)
    if single is not None:
        return (single,)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _manifest_error(
            "invalid_card_boxes",
            f"Expected {side} card boxes must be a list of valid boxes.",
            pair_index=pair_index,
        )
    parsed = tuple(_geometry_to_bbox(item) for item in value)
    if any(box is None for box in parsed):
        raise _manifest_error(
            "invalid_card_boxes",
            f"Expected {side} card boxes contain invalid geometry.",
            pair_index=pair_index,
        )
    return tuple(box for box in parsed if box is not None)


def _parse_expected(
    value: Any,
    pair_index: int,
) -> tuple[
    dict[str, str | None],
    dict[str, str | None],
    dict[str, tuple[tuple[float, float, float, float], ...]],
]:
    if not isinstance(value, Mapping):
        raise _manifest_error(
            "missing_expected_truth",
            "Each pair must contain an expected truth object.",
            pair_index=pair_index,
        )

    raw_fields = value.get("fields", {})
    if not isinstance(raw_fields, Mapping):
        raise _manifest_error(
            "invalid_field_truth",
            "expected.fields must be an object.",
            pair_index=pair_index,
        )
    fields: dict[str, str | None] = {}
    for field_name, truth in raw_fields.items():
        if field_name not in FIELD_NAMES:
            raise _manifest_error(
                "unknown_field_truth",
                "expected.fields contains an unsupported canonical field.",
                pair_index=pair_index,
            )
        if truth is not None and not isinstance(truth, str):
            raise _manifest_error(
                "invalid_field_truth",
                "Field truth values must be strings or null.",
                pair_index=pair_index,
            )
        fields[str(field_name)] = truth

    raw_urdu = value.get("urdu_text", {})
    if not isinstance(raw_urdu, Mapping):
        raise _manifest_error(
            "invalid_urdu_truth",
            "expected.urdu_text must be an object keyed by document side.",
            pair_index=pair_index,
        )
    urdu: dict[str, str | None] = {}
    for side, truth in raw_urdu.items():
        if side not in SIDES:
            raise _manifest_error(
                "invalid_urdu_truth_side",
                "Urdu truth must be keyed by front or back.",
                pair_index=pair_index,
            )
        if truth is not None and (not isinstance(truth, str) or not truth.strip()):
            raise _manifest_error(
                "invalid_urdu_truth",
                "Urdu truth must be a non-empty logical-order string or null.",
                pair_index=pair_index,
            )
        urdu[str(side)] = truth

    raw_boxes = value.get("card_boxes", {})
    if not isinstance(raw_boxes, Mapping):
        raise _manifest_error(
            "invalid_card_boxes",
            "expected.card_boxes must be an object keyed by document side.",
            pair_index=pair_index,
        )
    boxes: dict[str, tuple[tuple[float, float, float, float], ...]] = {}
    for side, side_boxes in raw_boxes.items():
        if side not in SIDES:
            raise _manifest_error(
                "invalid_card_box_side",
                "Card boxes must be keyed by front or back.",
                pair_index=pair_index,
            )
        boxes[str(side)] = _parse_box_collection(
            side_boxes,
            pair_index=pair_index,
            side=str(side),
        )
    return fields, urdu, boxes


def _safe_dataset_metadata(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key in ("name", "version", "license", "provenance"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            result[key] = " ".join(item.split())[:256]
    return result


def load_manifest(path: Path | str) -> EvaluationManifest:
    """Load and validate a grouped evaluation manifest without loading images."""

    manifest_path = Path(path).expanduser().resolve(strict=False)
    if not manifest_path.is_file():
        raise ManifestValidationError(
            "manifest_not_found",
            "The evaluation manifest file is absent.",
        )
    try:
        payload = manifest_path.read_bytes()
    except OSError as exc:
        raise ManifestValidationError(
            "manifest_unreadable",
            "The evaluation manifest could not be read.",
        ) from exc
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestValidationError(
            "manifest_invalid_json",
            "The evaluation manifest is not valid UTF-8 JSON.",
        ) from exc
    if not isinstance(raw, Mapping):
        raise ManifestValidationError(
            "manifest_invalid_shape",
            "The evaluation manifest root must be an object.",
        )
    if str(raw.get("schema_version", "")) not in {"1", "1.0"}:
        raise ManifestValidationError(
            "manifest_schema_unsupported",
            "The evaluation manifest schema_version must be 1.0.",
        )

    raw_pairs = raw.get("pairs")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise ManifestValidationError(
            "manifest_pairs_missing",
            "The evaluation manifest must contain at least one paired record.",
        )

    raw_threshold = raw.get("detection_iou_threshold", 0.5)
    threshold = _as_finite_number(raw_threshold)
    if threshold is None or not 0 < threshold <= 1:
        raise ManifestValidationError(
            "invalid_detection_iou_threshold",
            "detection_iou_threshold must be greater than zero and at most one.",
        )

    person_splits: dict[str, set[str]] = defaultdict(set)
    document_splits: dict[str, set[str]] = defaultdict(set)
    document_people: dict[str, set[str]] = defaultdict(set)
    pairs: list[EvaluationPair] = []
    for index, raw_pair in enumerate(raw_pairs):
        if not isinstance(raw_pair, Mapping):
            raise _manifest_error(
                "invalid_pair",
                "Each evaluation pair must be an object.",
                pair_index=index,
            )
        person_group = _validate_group_id(
            raw_pair.get("person_group_id"), "person_group_id", index
        )
        document_group = _validate_group_id(
            raw_pair.get("document_group_id"), "document_group_id", index
        )
        split = raw_pair.get("split")
        if split not in ALLOWED_SPLITS:
            raise _manifest_error(
                "invalid_split",
                "split must be train, validation, or held_out.",
                pair_index=index,
            )
        person_splits[person_group].add(str(split))
        document_splits[document_group].add(str(split))
        document_people[document_group].add(person_group)

        paths: dict[str, Path] = {}
        for side in SIDES:
            raw_path = raw_pair.get(f"{side}_path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise _manifest_error(
                    f"missing_{side}_path",
                    f"Each pair requires a {side}_path.",
                    pair_index=index,
                )
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                candidate = manifest_path.parent / candidate
            paths[side] = candidate.resolve(strict=False)

        fields, urdu, boxes = _parse_expected(raw_pair.get("expected"), index)
        pairs.append(
            EvaluationPair(
                index=index,
                split=str(split),
                front_path=paths["front"],
                back_path=paths["back"],
                expected_fields=fields,
                expected_urdu=urdu,
                expected_boxes=boxes,
            )
        )

    person_leaks = sum(len(splits) > 1 for splits in person_splits.values())
    document_leaks = sum(len(splits) > 1 for splits in document_splits.values())
    if person_leaks or document_leaks:
        raise ManifestValidationError(
            "group_split_leakage",
            "Person or document groups occur in more than one dataset split.",
            {
                "person_groups_with_leakage": person_leaks,
                "document_groups_with_leakage": document_leaks,
            },
        )
    mismatched_documents = sum(
        len(people) > 1 for people in document_people.values()
    )
    if mismatched_documents:
        raise ManifestValidationError(
            "document_group_person_mismatch",
            "A document group is associated with more than one person group.",
            {"mismatched_document_groups": mismatched_documents},
        )

    return EvaluationManifest(
        path=manifest_path,
        sha256=hashlib.sha256(payload).hexdigest(),
        dataset_metadata=_safe_dataset_metadata(raw.get("dataset")),
        detection_iou_threshold=threshold,
        pairs=tuple(pairs),
    )


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def environment_metadata() -> dict[str, Any]:
    """Return reproducibility metadata without hostnames or user information."""

    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "operating_system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "configured_device": str(getattr(settings, "KYC_DEVICE", "unknown")),
        "packages": {
            "Django": _package_version("Django"),
            "djangorestframework": _package_version("djangorestframework"),
            "easyocr": _package_version("easyocr"),
            "numpy": _package_version("numpy"),
            "onnxruntime": _package_version("onnxruntime"),
            "opencv-python-headless": _package_version("opencv-python-headless"),
            "Pillow": _package_version("Pillow"),
            "psutil": _package_version("psutil"),
        },
    }


def _empty_metrics(status: str, reason: str) -> dict[str, Any]:
    return {
        "field_exact_match": {"status": status, "reason": reason},
        "urdu_cer": {"status": status, "reason": reason},
        "card_detection": {"status": status, "reason": reason},
        "latency": {"status": status, "reason": reason},
        "memory": {"status": status, "reason": reason},
    }


def _base_report(
    *,
    status: str,
    split: str,
    blockers: list[dict[str, Any]],
    reason: str,
    manifest: EvaluationManifest | None = None,
) -> dict[str, Any]:
    dataset: dict[str, Any] = {
        "manifest_sha256": manifest.sha256 if manifest else None,
        "evaluated_split": split,
        "pair_count": 0,
    }
    if manifest:
        dataset.update(manifest.dataset_metadata)
    return {
        "schema_version": "1.0",
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset,
        "configuration": {
            "pipeline": "detector.pipeline.process_pair",
            "warm_latency": True,
        },
        "processing": {
            "attempted_pairs": 0,
            "successful_pairs": 0,
            "failed_pairs": 0,
            "error_codes": {},
        },
        "metrics": _empty_metrics(status, reason),
        "environment": environment_metadata(),
        "models": {},
        "blockers": blockers,
        "comparison": {
            "status": "unavailable",
            "reason": "benchmark_not_complete",
            "regressions": [],
        },
    }


def _manifest_failure_report(
    error: ManifestValidationError,
    *,
    split: str,
) -> dict[str, Any]:
    blocker = {"code": error.code, "message": error.message}
    if error.details:
        blocker["details"] = error.details
    return _base_report(
        status="not_run",
        split=split,
        blockers=[blocker],
        reason=error.code,
    )


def _asset_blockers(pairs: Sequence[EvaluationPair]) -> list[dict[str, Any]]:
    missing: dict[str, list[int]] = {side: [] for side in SIDES}
    unreadable: dict[str, list[int]] = {side: [] for side in SIDES}
    for pair in pairs:
        for side, path in (("front", pair.front_path), ("back", pair.back_path)):
            if not path.is_file():
                missing[side].append(pair.index)
                continue
            try:
                with path.open("rb") as handle:
                    handle.read(1)
            except OSError:
                unreadable[side].append(pair.index)

    blockers: list[dict[str, Any]] = []
    for side in SIDES:
        if missing[side]:
            blockers.append(
                {
                    "code": f"{side}_assets_missing",
                    "message": f"One or more {side} evaluation assets are absent.",
                    "details": {
                        "count": len(missing[side]),
                        "pair_indices": missing[side],
                    },
                }
            )
        if unreadable[side]:
            blockers.append(
                {
                    "code": f"{side}_assets_unreadable",
                    "message": f"One or more {side} evaluation assets cannot be read.",
                    "details": {
                        "count": len(unreadable[side]),
                        "pair_indices": unreadable[side],
                    },
                }
            )
    return blockers


def _load_default_processor() -> Callable[..., Mapping[str, Any]]:
    try:
        module = importlib.import_module("detector.pipeline")
    except Exception as exc:
        raise RuntimeError("pipeline_import_failed") from exc
    processor = getattr(module, "process_pair", None)
    if not callable(processor):
        raise RuntimeError("pipeline_entry_point_missing")
    return processor


def _content_type(path: Path) -> tuple[str, str]:
    suffix = path.suffix.casefold()
    mapping = {
        ".jpg": (".jpg", "image/jpeg"),
        ".jpeg": (".jpg", "image/jpeg"),
        ".png": (".png", "image/png"),
        ".webp": (".webp", "image/webp"),
    }
    return mapping.get(suffix, (".bin", "application/octet-stream"))


def _prepare_uploads(
    pair: EvaluationPair,
) -> tuple[SimpleUploadedFile, SimpleUploadedFile]:
    front_extension, front_type = _content_type(pair.front_path)
    back_extension, back_type = _content_type(pair.back_path)
    front = SimpleUploadedFile(
        f"front-benchmark{front_extension}",
        pair.front_path.read_bytes(),
        content_type=front_type,
    )
    try:
        back = SimpleUploadedFile(
            f"back-benchmark{back_extension}",
            pair.back_path.read_bytes(),
            content_type=back_type,
        )
    except Exception:
        front.close()
        raise
    return front, back


def _call_processor(
    processor: Callable[..., Mapping[str, Any]],
    front: SimpleUploadedFile,
    back: SimpleUploadedFile,
) -> dict[str, Any]:
    result = processor(front, back, f"benchmark-{uuid.uuid4().hex}")
    if not isinstance(result, Mapping):
        raise TypeError("pipeline_result_not_mapping")
    return dict(result)


def _invoke_processor(
    processor: Callable[..., Mapping[str, Any]],
    pair: EvaluationPair,
) -> dict[str, Any]:
    front, back = _prepare_uploads(pair)
    try:
        return _call_processor(processor, front, back)
    finally:
        front.close()
        back.close()


def _safe_error_code(value: Any) -> str:
    code = str(value or "processing_error")
    return code if re.fullmatch(r"[a-z0-9_]{1,64}", code) else "processing_error"


def _result_error_code(result: Mapping[str, Any]) -> str | None:
    error = result.get("error")
    if isinstance(error, Mapping):
        return _safe_error_code(error.get("code"))
    return None


def _pipeline_blocker(exc: Exception, pair_index: int | None = None) -> dict[str, Any]:
    details: dict[str, Any] = {"exception_type": type(exc).__name__}
    if pair_index is not None:
        details["pair_index"] = pair_index
    if isinstance(exc, KYCError):
        code = _safe_error_code(exc.code)
        if isinstance(exc.details, Mapping):
            for key in ("component", "reason", "exception_type"):
                value = exc.details.get(key)
                if isinstance(value, (str, int, float, bool)):
                    details[key] = value
        return {
            "code": code,
            "message": "The evaluation pipeline is unavailable.",
            "details": details,
        }
    reason = str(exc) if isinstance(exc, RuntimeError) else "pipeline_execution_failed"
    safe_reason = (
        reason
        if reason in {"pipeline_import_failed", "pipeline_entry_point_missing"}
        else "pipeline_execution_failed"
    )
    return {
        "code": safe_reason,
        "message": "The evaluation pipeline could not be executed.",
        "details": details,
    }


def _is_unavailable_error(exc: Exception) -> bool:
    return isinstance(exc, KYCError) and (
        exc.http_status >= 500 or exc.code == "model_unavailable"
    )


def _extract_fields(result: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("fields", "extracted_fields"):
        value = result.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _field_value(fields: Mapping[str, Any], field_name: str) -> Any:
    value = fields.get(field_name)
    if not isinstance(value, Mapping):
        return value
    for key in ("normalized_value", "value", "normalized"):
        if key in value:
            return value[key]
    return None


def _ocr_fragments(value: Any, side: str) -> list[str]:
    if isinstance(value, str):
        return [value] if _URDU_RE.search(value) else []
    if isinstance(value, Mapping):
        item_side = value.get("side") or value.get("expected_side")
        if item_side in SIDES and item_side != side:
            return []
        if side in value:
            return _ocr_fragments(value[side], side)
        for key in ("raw_detections", "items", "lines", "evidence", "results"):
            if key in value:
                return _ocr_fragments(value[key], side)
        for key in ("raw_text", "text", "normalized_text"):
            text = value.get(key)
            if isinstance(text, str):
                return [text] if _URDU_RE.search(text) else []
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        fragments: list[str] = []
        for item in value:
            fragments.extend(_ocr_fragments(item, side))
        return fragments
    return []


def _extract_urdu_text(result: Mapping[str, Any], side: str) -> str:
    for key in ("raw_ocr", "ocr", "ocr_evidence"):
        if key in result:
            fragments = _ocr_fragments(result[key], side)
            if fragments:
                return " ".join(fragments)
    return ""


def _normalize_cer_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _edit_distance(reference: str, prediction: str) -> int:
    if len(reference) < len(prediction):
        reference, prediction = prediction, reference
    previous = list(range(len(prediction) + 1))
    for row, reference_character in enumerate(reference, start=1):
        current = [row]
        for column, prediction_character in enumerate(prediction, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1]
                    + (reference_character != prediction_character),
                )
            )
        previous = current
    return previous[-1]


def _nested_side_candidates(result: Mapping[str, Any], side: str) -> list[Any]:
    candidates: list[Any] = []
    parents = [result]
    document = result.get("document")
    if isinstance(document, Mapping):
        parents.insert(0, document)
    for parent in parents:
        for key in ("sides", "preprocessing", "processed_sides", "detected_sides"):
            container = parent.get(key)
            if isinstance(container, Mapping) and side in container:
                candidates.append(container[side])
        if side in parent:
            candidates.append(parent[side])
        for key in ("detections", "card_detections"):
            if key in parent:
                container = parent[key]
                if isinstance(container, Mapping) and side in container:
                    candidates.append(container[side])
                elif isinstance(container, Sequence) and not isinstance(
                    container, (str, bytes, bytearray)
                ):
                    tagged = [
                        item
                        for item in container
                        if isinstance(item, Mapping)
                        and (item.get("side") or item.get("expected_side")) == side
                    ]
                    candidates.extend(tagged)
                else:
                    candidates.append(container)
    return candidates


def _boxes_from_value(value: Any) -> list[tuple[float, float, float, float]]:
    single = _geometry_to_bbox(value)
    if single is not None:
        return [single]
    if isinstance(value, Mapping):
        for key in ("detection", "detections", "boxes", "cards"):
            if key in value:
                return _boxes_from_value(value[key])
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result: list[tuple[float, float, float, float]] = []
        for item in value:
            result.extend(_boxes_from_value(item))
        return result
    return []


def _extract_predicted_boxes(
    result: Mapping[str, Any], side: str
) -> tuple[tuple[float, float, float, float], ...]:
    for candidate in _nested_side_candidates(result, side):
        boxes = _boxes_from_value(candidate)
        if boxes:
            # Stable de-duplication prevents one serialized box alias from being
            # counted as multiple detections.
            return tuple(dict.fromkeys(boxes))
    return ()


def _bbox_iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _match_detections(
    truth: Sequence[tuple[float, float, float, float]],
    predictions: Sequence[tuple[float, float, float, float]],
    threshold: float,
) -> tuple[int, int, int, list[float]]:
    candidates = sorted(
        (
            (_bbox_iou(truth_box, predicted_box), truth_index, predicted_index)
            for truth_index, truth_box in enumerate(truth)
            for predicted_index, predicted_box in enumerate(predictions)
        ),
        reverse=True,
    )
    used_truth: set[int] = set()
    used_predictions: set[int] = set()
    matched_ious: list[float] = []
    for iou, truth_index, predicted_index in candidates:
        if iou < threshold:
            break
        if truth_index in used_truth or predicted_index in used_predictions:
            continue
        used_truth.add(truth_index)
        used_predictions.add(predicted_index)
        matched_ious.append(iou)
    true_positives = len(matched_ious)
    return (
        true_positives,
        len(predictions) - true_positives,
        len(truth) - true_positives,
        matched_ious,
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _sanitize_models(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    allowed = {
        "name",
        "version",
        "sha256",
        "device",
        "providers",
        "languages",
        "confidence",
        "kind",
    }
    result: dict[str, Any] = {}
    for component, raw_metadata in value.items():
        if not isinstance(component, str) or not isinstance(raw_metadata, Mapping):
            continue
        metadata = {
            key: raw_metadata[key]
            for key in allowed
            if key in raw_metadata
            and isinstance(raw_metadata[key], (str, int, float, bool, list, tuple))
        }
        raw_weights = raw_metadata.get("weights")
        if isinstance(raw_weights, list):
            weights = []
            for raw_weight in raw_weights:
                if not isinstance(raw_weight, Mapping):
                    continue
                weights.append(
                    {
                        key: raw_weight[key]
                        for key in ("file", "bytes", "sha256")
                        if key in raw_weight
                        and isinstance(raw_weight[key], (str, int))
                    }
                )
            metadata["weights"] = weights
        result[component] = metadata
    return result


def _models_from_result(result: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("model_versions", "models"):
        models = _sanitize_models(result.get(key))
        if models:
            return models
    return {}


def _registry_models() -> dict[str, Any]:
    try:
        from .model_registry import get_model_registry

        return _sanitize_models(get_model_registry().versions())
    except Exception:
        return {}


def _default_rss_reader() -> Callable[[], int] | None:
    try:
        import psutil

        process = psutil.Process(os.getpid())
        return lambda: int(process.memory_info().rss)
    except (ImportError, OSError):
        return None


def _comparison_value(report: Mapping[str, Any], path: Sequence[str]) -> float | None:
    value: Any = report
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    number = _as_finite_number(value)
    return number


_COMPARISON_METRICS: Final[tuple[tuple[str, tuple[str, ...], str], ...]] = (
    (
        "field_exact_match.overall.accuracy",
        ("metrics", "field_exact_match", "overall", "accuracy"),
        "higher_is_better",
    ),
    ("urdu_cer.cer", ("metrics", "urdu_cer", "cer"), "lower_is_better"),
    (
        "card_detection.precision",
        ("metrics", "card_detection", "precision"),
        "higher_is_better",
    ),
    (
        "card_detection.recall",
        ("metrics", "card_detection", "recall"),
        "higher_is_better",
    ),
    (
        "card_detection.mean_iou",
        ("metrics", "card_detection", "mean_iou"),
        "higher_is_better",
    ),
    ("latency.p50_ms", ("metrics", "latency", "p50_ms"), "lower_is_better"),
    ("latency.p95_ms", ("metrics", "latency", "p95_ms"), "lower_is_better"),
    (
        "memory.observed_rss_delta_bytes",
        ("metrics", "memory", "observed_rss_delta_bytes"),
        "lower_is_better",
    ),
    (
        "memory.peak_rss_bytes",
        ("metrics", "memory", "peak_rss_bytes"),
        "lower_is_better",
    ),
)


def compare_with_baseline(
    current: Mapping[str, Any],
    baseline_path: Path | str | None,
) -> dict[str, Any]:
    """Compare fixed aggregate metrics with a compatible prior report."""

    if baseline_path is None:
        return {
            "status": "unavailable",
            "reason": "prior_baseline_not_provided",
            "comparisons": [],
            "regressions": [],
        }
    path = Path(baseline_path).expanduser().resolve(strict=False)
    if not path.is_file():
        return {
            "status": "unavailable",
            "reason": "prior_baseline_not_found",
            "comparisons": [],
            "regressions": [],
        }
    try:
        baseline = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "status": "unavailable",
            "reason": "prior_baseline_invalid",
            "comparisons": [],
            "regressions": [],
        }
    if not isinstance(baseline, Mapping) or baseline.get("status") != "complete":
        return {
            "status": "unavailable",
            "reason": "prior_baseline_incomplete",
            "comparisons": [],
            "regressions": [],
        }
    current_dataset = current.get("dataset", {})
    baseline_dataset = baseline.get("dataset", {})
    if (
        not isinstance(current_dataset, Mapping)
        or not isinstance(baseline_dataset, Mapping)
        or current_dataset.get("manifest_sha256")
        != baseline_dataset.get("manifest_sha256")
        or current_dataset.get("evaluated_split")
        != baseline_dataset.get("evaluated_split")
    ):
        return {
            "status": "unavailable",
            "reason": "prior_baseline_not_comparable",
            "comparisons": [],
            "regressions": [],
        }

    comparisons: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    for name, metric_path, direction in _COMPARISON_METRICS:
        current_value = _comparison_value(current, metric_path)
        baseline_value = _comparison_value(baseline, metric_path)
        if current_value is None or baseline_value is None:
            continue
        delta = current_value - baseline_value
        regressed = delta < 0 if direction == "higher_is_better" else delta > 0
        improved = delta > 0 if direction == "higher_is_better" else delta < 0
        comparison = {
            "metric": name,
            "direction": direction,
            "baseline": baseline_value,
            "current": current_value,
            "delta": round(delta, 6),
            "outcome": "regression" if regressed else "improvement" if improved else "unchanged",
        }
        comparisons.append(comparison)
        if regressed:
            regressions.append(comparison)
    if not comparisons:
        return {
            "status": "unavailable",
            "reason": "prior_baseline_has_no_comparable_metrics",
            "comparisons": [],
            "regressions": [],
        }
    return {
        "status": "complete",
        "reason": None,
        "has_regressions": bool(regressions),
        "comparisons": comparisons,
        "regressions": regressions,
    }


def run_benchmark(
    manifest_path: Path | str,
    *,
    split: str = "held_out",
    baseline_path: Path | str | None = None,
    detection_iou_threshold: float | None = None,
    warmup_pairs: int = 1,
    processor: Callable[..., Mapping[str, Any]] | None = None,
    clock: Callable[[], float] = time.perf_counter,
    rss_reader: Callable[[], int] | None | object = _AUTO_RSS,
) -> dict[str, Any]:
    """Evaluate one split and return an aggregate JSON-ready report."""

    try:
        manifest = load_manifest(manifest_path)
    except ManifestValidationError as exc:
        return _manifest_failure_report(exc, split=split)

    if split not in ALLOWED_SPLITS:
        error = ManifestValidationError(
            "invalid_evaluation_split",
            "Evaluation split must be train, validation, or held_out.",
        )
        return _manifest_failure_report(error, split=split)
    selected_pairs = tuple(pair for pair in manifest.pairs if pair.split == split)
    if not selected_pairs:
        return _base_report(
            status="not_run",
            split=split,
            blockers=[
                {
                    "code": "evaluation_split_empty",
                    "message": "The requested evaluation split contains no pairs.",
                }
            ],
            reason="evaluation_split_empty",
            manifest=manifest,
        )
    if not isinstance(warmup_pairs, int) or isinstance(warmup_pairs, bool) or warmup_pairs < 1:
        return _base_report(
            status="not_run",
            split=split,
            blockers=[
                {
                    "code": "invalid_warmup_pairs",
                    "message": "warmup_pairs must be a positive integer.",
                }
            ],
            reason="invalid_warmup_pairs",
            manifest=manifest,
        )
    threshold = (
        manifest.detection_iou_threshold
        if detection_iou_threshold is None
        else _as_finite_number(detection_iou_threshold)
    )
    if threshold is None or not 0 < threshold <= 1:
        return _base_report(
            status="not_run",
            split=split,
            blockers=[
                {
                    "code": "invalid_detection_iou_threshold",
                    "message": "Detection IoU threshold must be in (0, 1].",
                }
            ],
            reason="invalid_detection_iou_threshold",
            manifest=manifest,
        )

    blockers = _asset_blockers(selected_pairs)
    if blockers:
        report = _base_report(
            status="not_run",
            split=split,
            blockers=blockers,
            reason="evaluation_assets_unavailable",
            manifest=manifest,
        )
        report["dataset"]["pair_count"] = len(selected_pairs)
        report["configuration"]["detection_iou_threshold"] = threshold
        return report

    if processor is None:
        try:
            processor = _load_default_processor()
        except Exception as exc:
            report = _base_report(
                status="unavailable",
                split=split,
                blockers=[_pipeline_blocker(exc)],
                reason="pipeline_unavailable",
                manifest=manifest,
            )
            report["dataset"]["pair_count"] = len(selected_pairs)
            return report

    resolved_rss_reader = (
        _default_rss_reader() if rss_reader is _AUTO_RSS else rss_reader
    )
    memory_samples: list[int] = []
    memory_available = callable(resolved_rss_reader)

    def sample_memory() -> None:
        nonlocal memory_available
        if not memory_available or not callable(resolved_rss_reader):
            return
        try:
            value = int(resolved_rss_reader())
            if value < 0:
                raise ValueError("negative_rss")
            memory_samples.append(value)
        except Exception:
            memory_available = False
            memory_samples.clear()

    sample_memory()
    model_metadata: dict[str, Any] = {}
    for warmup_index in range(warmup_pairs):
        pair = selected_pairs[warmup_index % len(selected_pairs)]
        try:
            warm_result = _invoke_processor(processor, pair)
            if not model_metadata:
                model_metadata = _models_from_result(warm_result)
        except Exception as exc:
            if _is_unavailable_error(exc) or not isinstance(exc, KYCError):
                report = _base_report(
                    status="unavailable",
                    split=split,
                    blockers=[_pipeline_blocker(exc, pair.index)],
                    reason="pipeline_unavailable",
                    manifest=manifest,
                )
                report["dataset"]["pair_count"] = len(selected_pairs)
                return report
            # A normal 4xx processing outcome does not expose any truth and is
            # measured again in the evaluation loop as a failed prediction.
    sample_memory()

    field_stats = {field: [0, 0] for field in FIELD_NAMES}
    cer_edits = cer_characters = cer_samples = 0
    detection_tp = detection_fp = detection_fn = detection_sides = 0
    matched_ious: list[float] = []
    latencies_ms: list[float] = []
    processing_errors: Counter[str] = Counter()
    successful_pairs = 0

    for pair in selected_pairs:
        try:
            front_upload, back_upload = _prepare_uploads(pair)
        except OSError as exc:
            report = _base_report(
                status="unavailable",
                split=split,
                blockers=[
                    {
                        "code": "evaluation_asset_read_failed",
                        "message": "An evaluation asset became unreadable during the run.",
                        "details": {
                            "pair_index": pair.index,
                            "exception_type": type(exc).__name__,
                        },
                    }
                ],
                reason="evaluation_asset_read_failed",
                manifest=manifest,
            )
            report["dataset"]["pair_count"] = len(selected_pairs)
            report["processing"]["attempted_pairs"] = len(latencies_ms)
            return report

        started = clock()
        result: dict[str, Any]
        pipeline_exception: Exception | None = None
        try:
            result = _call_processor(processor, front_upload, back_upload)
            result_error = _result_error_code(result)
            if result_error:
                processing_errors[result_error] += 1
            else:
                successful_pairs += 1
        except Exception as exc:
            pipeline_exception = exc
            result = {}
        finally:
            try:
                finished = clock()
            finally:
                front_upload.close()
                back_upload.close()

        if pipeline_exception is not None:
            if _is_unavailable_error(pipeline_exception) or not isinstance(
                pipeline_exception, KYCError
            ):
                report = _base_report(
                    status="unavailable",
                    split=split,
                    blockers=[_pipeline_blocker(pipeline_exception, pair.index)],
                    reason="pipeline_unavailable",
                    manifest=manifest,
                )
                report["dataset"]["pair_count"] = len(selected_pairs)
                report["processing"]["attempted_pairs"] = len(latencies_ms) + 1
                return report
            processing_errors[_safe_error_code(pipeline_exception.code)] += 1

        elapsed_ms = max(0.0, (finished - started) * 1000.0)
        latencies_ms.append(elapsed_ms)
        sample_memory()

        if not model_metadata:
            model_metadata = _models_from_result(result)
        predicted_fields = _extract_fields(result)
        for field_name, truth in pair.expected_fields.items():
            if truth is None:
                continue
            field_stats[field_name][1] += 1
            if _field_value(predicted_fields, field_name) == truth:
                field_stats[field_name][0] += 1

        for side, truth in pair.expected_urdu.items():
            if truth is None:
                continue
            reference = _normalize_cer_text(truth)
            prediction = _normalize_cer_text(_extract_urdu_text(result, side))
            cer_edits += _edit_distance(reference, prediction)
            cer_characters += len(reference)
            cer_samples += 1

        for side, truth_boxes in pair.expected_boxes.items():
            predictions = _extract_predicted_boxes(result, side)
            tp, fp, fn, ious = _match_detections(
                truth_boxes, predictions, threshold
            )
            detection_tp += tp
            detection_fp += fp
            detection_fn += fn
            matched_ious.extend(ious)
            detection_sides += 1

    correct = sum(value[0] for value in field_stats.values())
    total = sum(value[1] for value in field_stats.values())
    per_field = {
        name: (
            {
                "status": "complete",
                "correct": values[0],
                "total": values[1],
                "accuracy": _ratio(values[0], values[1]),
            }
            if values[1]
            else {"status": "not_run", "reason": "field_truth_missing"}
        )
        for name, values in field_stats.items()
    }
    field_metric: dict[str, Any]
    if total:
        field_accuracies = [
            values[0] / values[1] for values in field_stats.values() if values[1]
        ]
        field_metric = {
            "status": "complete",
            "definition": "Exact equality of canonical pipeline normalized_value and manifest truth.",
            "overall": {
                "correct": correct,
                "total": total,
                "accuracy": _ratio(correct, total),
                "macro_accuracy": round(statistics.fmean(field_accuracies), 6),
            },
            "per_field": per_field,
        }
    else:
        field_metric = {
            "status": "not_run",
            "reason": "field_truth_missing",
            "per_field": per_field,
        }

    if cer_characters:
        cer_metric: dict[str, Any] = {
            "status": "complete",
            "definition": "Levenshtein edits/reference characters after Unicode NFC and whitespace normalization.",
            "samples": cer_samples,
            "edit_distance": cer_edits,
            "reference_characters": cer_characters,
            "cer": round(cer_edits / cer_characters, 6),
        }
    else:
        cer_metric = {"status": "not_run", "reason": "urdu_truth_missing"}

    if detection_sides:
        detection_metric: dict[str, Any] = {
            "status": "complete",
            "definition": "Greedy one-to-one axis-aligned envelope matching at the configured IoU threshold.",
            "coordinate_space": "source_image_pixels",
            "iou_threshold": threshold,
            "evaluated_sides": detection_sides,
            "true_positives": detection_tp,
            "false_positives": detection_fp,
            "false_negatives": detection_fn,
            "precision": _ratio(detection_tp, detection_tp + detection_fp),
            "recall": _ratio(detection_tp, detection_tp + detection_fn),
            "mean_iou": (
                round(statistics.fmean(matched_ious), 6) if matched_ious else None
            ),
            "matched_detections": len(matched_ious),
        }
    else:
        detection_metric = {
            "status": "not_run",
            "reason": "card_box_truth_missing",
            "iou_threshold": threshold,
        }

    latency_metric = {
        "status": "complete",
        "definition": "Warm in-process process_pair wall-clock latency; asset reads and warm-up calls excluded.",
        "unit": "milliseconds",
        "samples": len(latencies_ms),
        "p50_ms": round(_percentile(latencies_ms, 0.50), 3),
        "p95_ms": round(_percentile(latencies_ms, 0.95), 3),
        "minimum_ms": round(min(latencies_ms), 3),
        "maximum_ms": round(max(latencies_ms), 3),
    }

    if memory_available and len(memory_samples) >= 2:
        baseline_rss = memory_samples[0]
        warm_rss = memory_samples[1]
        peak_rss = max(memory_samples)
        memory_metric: dict[str, Any] = {
            "status": "complete",
            "definition": "Process RSS observed before warm-up, after warm-up, and after each measured pair.",
            "baseline_rss_bytes": baseline_rss,
            "warm_rss_bytes": warm_rss,
            "peak_rss_bytes": peak_rss,
            "observed_rss_delta_bytes": max(0, peak_rss - baseline_rss),
            "warm_loop_delta_bytes": max(0, peak_rss - warm_rss),
            "sample_count": len(memory_samples),
        }
    else:
        memory_metric = {
            "status": "unavailable",
            "reason": "rss_measurement_unavailable",
        }

    metric_blockers: list[dict[str, Any]] = []
    for metric_name, metric in (
        ("field_exact_match", field_metric),
        ("urdu_cer", cer_metric),
        ("card_detection", detection_metric),
        ("memory", memory_metric),
    ):
        if metric["status"] in {"not_run", "unavailable"}:
            metric_blockers.append(
                {
                    "code": str(metric["reason"]),
                    "message": f"The {metric_name} metric was not produced.",
                    "details": {"metric": metric_name},
                }
            )

    report = {
        "schema_version": "1.0",
        "status": "complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            **manifest.dataset_metadata,
            "manifest_sha256": manifest.sha256,
            "evaluated_split": split,
            "pair_count": len(selected_pairs),
        },
        "configuration": {
            "pipeline": "detector.pipeline.process_pair",
            "detection_iou_threshold": threshold,
            "warmup_pairs": warmup_pairs,
            "latency_percentiles": "linear_interpolation",
        },
        "processing": {
            "attempted_pairs": len(selected_pairs),
            "successful_pairs": successful_pairs,
            "failed_pairs": len(selected_pairs) - successful_pairs,
            "error_codes": dict(sorted(processing_errors.items())),
        },
        "metrics": {
            "field_exact_match": field_metric,
            "urdu_cer": cer_metric,
            "card_detection": detection_metric,
            "latency": latency_metric,
            "memory": memory_metric,
        },
        "environment": environment_metadata(),
        "models": model_metadata or _registry_models(),
        "blockers": metric_blockers,
    }
    report["comparison"] = compare_with_baseline(report, baseline_path)
    return report


__all__ = [
    "ALLOWED_SPLITS",
    "EvaluationManifest",
    "EvaluationPair",
    "FIELD_NAMES",
    "ManifestValidationError",
    "compare_with_baseline",
    "environment_metadata",
    "load_manifest",
    "run_benchmark",
]
