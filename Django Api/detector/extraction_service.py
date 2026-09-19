from __future__ import annotations

import logging
from typing import Any
import numpy as np
from django.db import transaction
from django.utils import timezone

from .model_registry import get_model_registry
from .models import DocumentArtifact, ExtractionRevision, KYCApplication, Organization
from .normalization import normalize_text, order_ocr_items
from .ocr import recognize_text
from .parsing import TEMPLATE_FIELDS, parse_fields
from .preprocessing import preprocess_document
from .side_detection import classify_document_side
from .uploads import ValidatedImage, validate_upload

logger = logging.getLogger(__name__)


def auto_extract_and_store(
    application: KYCApplication,
    kind: str,
    validated: ValidatedImage,
    template: str = "generic",
) -> dict[str, Any]:
    """Auto-detect all CNIC details from an uploaded artifact and persist to database.

    Args:
        application: The KYCApplication model instance receiving the artifact.
        kind: The artifact slot ('front' or 'back'). Non-card artifacts return an empty dict.
        validated: Decoded and verified ValidatedImage instance containing card pixels.
        template: Template layout to use for field parsing (defaults to 'generic').

    Returns:
        A dictionary mapping field names to their raw and normalized extracted values.

    Side effects:
        Creates or updates ExtractionRevision records with Source.MACHINE in the database.
    """
    if kind not in {"front", "back"}:
        return {}

    registry = get_model_registry()
    detector = registry.get_card_detector()

    # Step 1: Preprocess and extract OCR for current image
    ocr_by_side: dict[str, list[dict[str, Any]]] = {}
    current_ocr = _recognize_image(validated, kind, detector)
    ocr_by_side[kind] = current_ocr

    # Step 2: Check if opposite side is already stored in application artifacts
    opposite_kind = "back" if kind == "front" else "front"
    opposite_artifact = application.artifacts.filter(
        kind=opposite_kind, deleted_at__isnull=True
    ).order_by("-created_at").first()

    if opposite_artifact:
        try:
            from django.core.files.uploadedfile import SimpleUploadedFile
            from .object_storage import get_object_store
            store = get_object_store()
            opp_bytes = store.get(opposite_artifact.storage_key)
            opp_validated = validate_upload(SimpleUploadedFile(f"{opposite_kind}.bin", opp_bytes), opposite_kind)
            opp_ocr = _recognize_image(opp_validated, opposite_kind, detector)
            ocr_by_side[opposite_kind] = opp_ocr
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read opposite side artifact for extraction: %s", exc)

    # Step 3: Order OCR and parse fields
    ordered_ocr = {
        side: order_ocr_items(items, direction="auto", side=side)
        for side, items in ocr_by_side.items()
    }
    parsed = parse_fields(ordered_ocr, template=template)

    # Step 4: Persist extracted fields to ExtractionRevision in database
    extracted_summary: dict[str, Any] = {}
    with transaction.atomic():
        for field_name, entry in parsed.items():
            raw_val = entry.get("raw_value")
            norm_val = entry.get("normalized_value")
            if raw_val is not None or norm_val is not None:
                extracted_summary[field_name] = {
                    "raw_value": raw_val,
                    "normalized_value": norm_val,
                    "source": "machine",
                }
                ExtractionRevision.objects.update_or_create(
                    application=application,
                    field_name=field_name,
                    source=ExtractionRevision.Source.MACHINE,
                    defaults={
                        "raw_value": raw_val,
                        "normalized_value": norm_val,
                        "evidence": {"items": entry.get("evidence", [])},
                    },
                )

    return extracted_summary


def detect_and_store_single_image(
    upload,
    *,
    side: str = "auto",
    organization: Organization | None = None,
    user=None,
    external_reference: str = "",
    template: str = "generic",
) -> dict[str, Any]:
    """Standalone helper: accept a CNIC image, auto-detect all details, and save to DB."""
    validated = validate_upload(upload, "front" if side == "auto" else side)
    registry = get_model_registry()
    detector = registry.get_card_detector()

    # Process card image and run OCR once
    requested_side = "front" if side == "auto" else side
    ocr_items = _recognize_image(validated, requested_side, detector)

    # Classify document side from OCR results if auto
    if side == "auto":
        side_classification = classify_document_side(validated.bgr_image, ocr_items)
        candidate = side_classification.get("detected_side")
        detected_side = candidate if candidate in {"front", "back"} else "front"
    else:
        detected_side = side if side in {"front", "back"} else "front"

    from dataclasses import replace
    validated = replace(validated, side=detected_side)

    ordered_ocr = {
        detected_side: order_ocr_items(ocr_items, direction="auto", side=detected_side)
    }
    parsed = parse_fields(ordered_ocr, template=template)

    # If organization not given, find or create default
    if organization is None:
        organization = Organization.objects.first()
        if organization is None:
            organization = Organization.objects.create(name="Default Organization", slug="default")

    # Create application and store artifact + extraction revisions
    with transaction.atomic():
        application = KYCApplication.objects.create(
            organization=organization,
            applicant=user if getattr(user, "pk", None) else None,
            external_reference=external_reference or f"AUTO-{timezone.now().strftime('%Y%m%d%H%M%S')}",
            workflow="cnic_auto_detect",
        )
        from .application_service import save_artifact
        artifact, _, _ = save_artifact(application, detected_side, upload)

        extracted_fields: dict[str, Any] = {}
        for field_name, entry in parsed.items():
            raw_val = entry.get("raw_value")
            norm_val = entry.get("normalized_value")
            if raw_val is not None or norm_val is not None:
                extracted_fields[field_name] = {
                    "raw_value": raw_val,
                    "normalized_value": norm_val,
                    "source": "machine",
                }
                ExtractionRevision.objects.create(
                    application=application,
                    field_name=field_name,
                    raw_value=raw_val,
                    normalized_value=norm_val,
                    evidence={"items": entry.get("evidence", [])},
                    source=ExtractionRevision.Source.MACHINE,
                )

    return {
        "application_id": str(application.pk),
        "display_id": application.display_id,
        "artifact_id": str(artifact.pk),
        "detected_side": detected_side,
        "extracted_fields": extracted_fields,
        "raw_ocr_count": len(ocr_items),
    }


def _recognize_image(validated: ValidatedImage, side: str, detector) -> list[dict[str, Any]]:
    """Crop/rectify card image if possible; gracefully fall back to full image OCR."""
    ocr_image = validated.bgr_image
    try:
        model_detections = detector.detect(validated.bgr_image) if detector is not None else []
        prep = preprocess_document(validated, side, model_detections=model_detections)
        if prep.corrected_image is not None and prep.corrected_image.size > 0:
            ocr_image = prep.corrected_image
    except Exception as exc:  # noqa: BLE001
        logger.debug("Card detection fallback to raw image for %s: %s", side, exc)

    return recognize_text(ocr_image, side)
