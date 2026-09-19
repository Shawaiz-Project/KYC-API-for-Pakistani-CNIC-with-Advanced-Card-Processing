from __future__ import annotations

import hashlib
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .duplicates import find_duplicate_signals, perceptual_dhash
from .models import AuditEvent, DocumentArtifact, DuplicateFingerprint
from .object_storage import get_object_store
from .uploads import ValidatedImage, validate_upload


CONTENT_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def save_artifact(application, kind: str, upload, request_id: str = "") -> tuple[DocumentArtifact, ValidatedImage, list[dict]]:
    validated = validate_upload(upload, kind)
    digest = hashlib.sha256(validated.original_bytes).hexdigest()
    dhash = perceptual_dhash(validated.bgr_image)
    signals = find_duplicate_signals(application.organization, application, digest, dhash)
    store = get_object_store()
    content_type = CONTENT_TYPES.get(str(validated.actual_format).lower(), "image/jpeg")
    key = store.put(str(application.organization_id), str(application.pk), kind, validated.original_bytes, content_type)
    artifact = DocumentArtifact.objects.create(
        application=application,
        kind=kind,
        storage_key=key,
        content_type=content_type,
        byte_size=len(validated.original_bytes),
        width=validated.width,
        height=validated.height,
        sha256=digest,
        metadata=validated.metadata(),
        expires_at=timezone.now() + timedelta(hours=application.organization.retention_hours),
    )
    DuplicateFingerprint.objects.create(
        organization=application.organization,
        application=application,
        artifact=artifact,
        sha256=digest,
        perceptual_hash=dhash,
    )
    AuditEvent.objects.create(
        organization=application.organization,
        application=application,
        actor=application.applicant,
        event_type="artifact_uploaded",
        safe_details={"kind": kind, "byte_size": len(validated.original_bytes), "duplicate_signal_count": len(signals)},
        request_id=request_id,
    )
    return artifact, validated, signals


def latest_artifact(application, kind: str) -> DocumentArtifact | None:
    return application.artifacts.filter(kind=kind, deleted_at__isnull=True).order_by("-created_at").first()
