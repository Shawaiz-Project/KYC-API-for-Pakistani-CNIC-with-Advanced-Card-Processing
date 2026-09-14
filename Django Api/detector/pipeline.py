from __future__ import annotations

import time
from typing import Any

import cv2
from django.conf import settings
from rest_framework import status

from .errors import KYCError
from .model_registry import get_model_registry
from .normalization import normalize_text, order_ocr_items
from .ocr import recognize_text
from .parsing import TEMPLATE_FIELDS, parse_fields
from .preprocessing import PreprocessingResult, preprocess_document
from .serialization import separate_fields
from .side_detection import classify_document_side
from .storage import RequestStorage
from .uploads import ValidatedImage, validate_upload
from .validation import CHECK_STATUSES, validate_fields


def process_pair(front_upload, back_upload, request_id: str, template: str = "generic") -> dict[str, Any]:
    """Run the v1 CNIC processing pipeline without making an issuance claim."""

    started = time.perf_counter()
    requested_template = str(template or "generic").strip().casefold()
    template_key = "generic" if requested_template == "auto" else requested_template
    if template_key not in TEMPLATE_FIELDS:
        raise KYCError(
            "unsupported_document_layout",
            "The requested CNIC layout is not supported.",
            status.HTTP_400_BAD_REQUEST,
            {"supported_layouts": sorted(TEMPLATE_FIELDS)},
        )
    front = validate_upload(front_upload, "front")
    back = validate_upload(back_upload, "back")
    registry = get_model_registry()
    detector = registry.get_card_detector()

    with RequestStorage.create() as storage:
        storage.save_original("front", front.original_bytes)
        storage.save_original("back", back.original_bytes)

        front_processed, front_model = _preprocess(front, "front", detector)
        back_processed, back_model = _preprocess(back, "back", detector)
        storage.save_processing_copy("front", _encode_processing_copy(front_processed.corrected_image))
        storage.save_processing_copy("back", _encode_processing_copy(back_processed.corrected_image))

        front_ocr = recognize_text(front_processed.corrected_image, "front")
        back_ocr = recognize_text(back_processed.corrected_image, "back")

        front_side = classify_document_side(front_processed.corrected_image, front_ocr)
        back_side = classify_document_side(back_processed.corrected_image, back_ocr)
        _reject_wrong_side("front", front_side, front_processed)
        _reject_wrong_side("back", back_side, back_processed)

        # Preserve only a syntactically recognized CNIC candidate from the QR
        # decoder, never its full payload. This lets validation compare sides.
        if back_side.get("qr_cnic"):
            back_ocr.append(
                {
                    "side": "back",
                    "raw_text": back_side["qr_cnic"],
                    "normalized_text": normalize_text(back_side["qr_cnic"]),
                    "bbox": [],
                    "confidence": {
                        "value": None,
                        "type": "decoder_result",
                        "calibrated": False,
                    },
                    "field": "cnic_number",
                }
            )

        ordered_ocr = {
            "front": order_ocr_items(front_ocr, direction="auto", side="front"),
            "back": order_ocr_items(back_ocr, direction="auto", side="back"),
        }
        parsed = parse_fields(ordered_ocr, template=template_key)
        ocr_runtime_status = _mark_unavailable_ocr_fields(parsed, registry.versions())
        validation = validate_fields(parsed, template=template_key)
        _add_side_checks(validation, front_side, back_side)
        extracted, evidence = separate_fields(parsed)

        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return {
            "request_id": request_id,
            "api_version": "v1",
            "processing": {
                "success": True,
                "status": "completed",
                "duration_ms": elapsed_ms,
            },
            "verification": {
                "decision": _verification_decision(validation),
                "authoritative_issuance_checked": False,
                "message": "Local extraction and syntax checks are not proof of issuance, authenticity, or bearer identity.",
            },
            "document": {
                "type": "pakistani_cnic",
                "layout": template_key,
                "layout_status": "uncertain" if requested_template == "auto" else "provided",
                "detected_sides": {
                    "front_upload": _public_side(front_side),
                    "back_upload": _public_side(back_side),
                },
                "detections": {
                    "front": [_detection_record(front_processed, front_model)],
                    "back": [_detection_record(back_processed, back_model)],
                },
            },
            "quality": {
                "overall_status": _quality_status(front_processed, back_processed),
                "front": [item.as_dict() for item in front_processed.quality_findings],
                "back": [item.as_dict() for item in back_processed.quality_findings],
            },
            "extracted_fields": extracted,
            "field_evidence": evidence,
            "ocr": {
                "engine": "EasyOCR",
                "status": ocr_runtime_status,
                "raw_detections": ordered_ocr,
                "ordering": "top_to_bottom_with_per_line_unicode_direction",
                "rotation_candidates_degrees": list(settings.KYC_OCR_ROTATION_INFO),
            },
            "validation": validation,
            "model_versions": registry.versions(),
        }


def _mark_unavailable_ocr_fields(
    parsed: dict[str, dict[str, Any]], model_versions: dict[str, dict[str, Any]]
) -> str:
    configured_status = model_versions.get("ocr", {}).get("status")
    if configured_status not in {"unavailable", "disabled"}:
        return "available"
    for entry in parsed.values():
        if entry.get("supported") and entry.get("normalized_value") is None:
            entry["availability"] = "unavailable"
    return str(configured_status)


def _preprocess(validated: ValidatedImage, side: str, detector):
    model_detections = detector.detect(validated.bgr_image) if detector is not None else []
    if len(model_detections) > 1:
        raise KYCError(
            "multiple_cards_detected",
            "More than one card was detected in one upload.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"side": side, "card_count": len(model_detections), "recapture_reasons": ["multiple_cards"]},
        )
    return preprocess_document(validated, side, model_detections=model_detections), model_detections


def _encode_processing_copy(image) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise KYCError(
            "processing_copy_failed",
            "A private processing copy could not be encoded.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return encoded.tobytes()


def _reject_wrong_side(expected: str, result: dict[str, Any], preprocessing: PreprocessingResult) -> None:
    detected = result.get("detected_side")
    if detected in {"front", "back"} and detected != expected:
        raise KYCError(
            "wrong_document_side",
            f"The {expected} upload appears to contain the {detected} side.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {
                "expected_side": expected,
                "detected_side": detected,
                "detection": preprocessing.detection.as_dict(),
                "recapture_reasons": ["wrong_side"],
            },
        )


def _side_check(expected: str, result: dict[str, Any]) -> dict[str, Any]:
    detected = result.get("detected_side")
    if detected == expected:
        return {"status": "pass", "code": f"{expected}_side_detected", "message": f"The {expected} side was detected."}
    if detected in {"front", "back"}:
        return {"status": "fail", "code": f"wrong_{expected}_side", "message": f"The {expected} slot contains the wrong side."}
    return {
        "status": "uncertain",
        "code": f"{expected}_side_uncertain",
        "message": f"The {expected} side could not be classified confidently.",
    }


def _add_side_checks(validation: dict[str, Any], front: dict[str, Any], back: dict[str, Any]) -> None:
    validation["checks"]["front_side"] = _side_check("front", front)
    validation["checks"]["back_side"] = _side_check("back", back)
    statuses = {check.get("status") for check in validation["checks"].values()}
    if not statuses <= CHECK_STATUSES:
        raise RuntimeError("A validation check produced an unsupported status")
    if "fail" in statuses:
        validation["overall_status"] = "fail"
    elif "unavailable" in statuses:
        validation["overall_status"] = "unavailable"
    elif "uncertain" in statuses:
        validation["overall_status"] = "uncertain"
    elif "pass" in statuses:
        validation["overall_status"] = "pass"
    else:
        validation["overall_status"] = "not_run"


def _verification_decision(validation: dict[str, Any]) -> str:
    overall = validation.get("overall_status")
    if overall == "pass":
        return "pass"
    if overall == "fail":
        return "fail"
    return "uncertain"


def _quality_status(*results: PreprocessingResult) -> str:
    statuses = {finding.status for result in results for finding in result.quality_findings}
    return "fail" if "fail" in statuses else "pass"


def _public_side(side: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in side.items() if key != "qr_cnic"}


def _detection_record(result: PreprocessingResult, model_detections: list[dict[str, Any]]) -> dict[str, Any]:
    detection = result.detection.as_dict()
    detection["polygon"] = detection.pop("corners")
    detection["score"] = {
        "value": detection["area_ratio"],
        "type": "heuristic_area_ratio",
        "calibrated": False,
    }
    if model_detections:
        model_item = model_detections[0]
        detection["model_evidence"] = {
            "bbox": model_item.get("bbox"),
            "class_id": model_item.get("class_id"),
            "confidence": {
                "value": model_item.get("score"),
                "type": "raw_detector_score",
                "calibrated": False,
            },
        }
    return detection
