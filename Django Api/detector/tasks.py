from __future__ import annotations

from io import BytesIO

import cv2
import numpy as np
from celery import shared_task
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from .application_service import latest_artifact
from .duplicates import find_duplicate_signals, identifier_hmac, perceptual_dhash
from .checks.base import DetectorInput
from .checks.registry import run_configured_detectors
from .errors import KYCError
from .models import CheckResult, ExtractionRevision, KYCApplication, ProcessingJob, ReviewDecision
from .object_storage import get_object_store
from .pipeline import process_pair
from .policy import decide


def _image(content: bytes):
    return cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)


@shared_task(bind=True, autoretry_for=(OSError,), retry_backoff=True, retry_jitter=True, max_retries=2)
def process_application_task(self, application_id: str):
    with transaction.atomic():
        application = KYCApplication.objects.select_for_update().select_related("organization").get(pk=application_id)
        job, _ = ProcessingJob.objects.select_for_update().get_or_create(application=application)
        if application.state == KYCApplication.State.COMPLETED and job.state == ProcessingJob.State.COMPLETED:
            return {"application_id": application_id, "state": "completed", "idempotent": True}
        application.state = KYCApplication.State.PROCESSING
        application.processing_started_at = timezone.now()
        application.failure_code = ""
        application.save(update_fields=("state", "processing_started_at", "failure_code", "updated_at"))
        job.state = ProcessingJob.State.RUNNING
        job.attempts += 1
        job.task_id = getattr(self.request, "id", "") or job.task_id
        job.heartbeat_at = timezone.now()
        job.save()

    store = get_object_store()
    front_artifact = latest_artifact(application, "front")
    back_artifact = latest_artifact(application, "back")
    selfie_artifact = latest_artifact(application, "selfie")
    if not front_artifact or not back_artifact or not selfie_artifact:
        return _terminal_failure(application_id, "required_artifact_missing")
    front_bytes = store.get(front_artifact.storage_key)
    back_bytes = store.get(back_artifact.storage_key)
    selfie_bytes = store.get(selfie_artifact.storage_key)

    try:
        phase1 = process_pair(
            SimpleUploadedFile("front.bin", front_bytes, content_type=front_artifact.content_type),
            SimpleUploadedFile("back.bin", back_bytes, content_type=back_artifact.content_type),
            f"application-{application_id}",
            template="auto",
        )
    except KYCError as exc:
        if exc.http_status == 422:
            return _terminal_recapture(application_id, exc.code, exc.details)
        return _terminal_failure(application_id, exc.code)

    duplicate_signals = []
    for fingerprint in application.fingerprints.select_related("artifact"):
        # Signals were computed before the new fingerprint was written and are
        # intentionally rebuilt without exposing hashes in the API response.
        matches = application.organization.fingerprints.filter(sha256=fingerprint.sha256).exclude(application=application)
        if matches.exists():
            duplicate_signals.append({"reason": "identical_file", "artifact_kind": fingerprint.artifact.kind if fingerprint.artifact else "unknown"})
    phase1["duplicate_signals"] = duplicate_signals
    cnic = phase1.get("extracted_fields", {}).get("cnic_number", {})
    cnic_value = cnic.get("normalized_value")
    cnic_evidence = phase1.get("field_evidence", {}).get("cnic_number", [])
    confidences = [item.get("confidence", {}).get("value") for item in cnic_evidence]
    reliable_confidences = [float(value) for value in confidences if isinstance(value, (int, float))]
    cnic_syntax = phase1.get("validation", {}).get("checks", {}).get("cnic_syntax", {}).get("status")
    if cnic_value and reliable_confidences and max(reliable_confidences) >= 0.85 and cnic_syntax == "pass":
        digest = identifier_hmac(str(cnic_value))
        if digest:
            identifier_signals = find_duplicate_signals(application.organization, application, "", "", digest)
            duplicate_signals.extend(identifier_signals)
            application.fingerprints.update(identifier_hmac=digest, identifier_confidence=max(reliable_confidences))
    liveness_session = application.liveness_sessions.order_by("-created_at").first()
    liveness = {}
    if liveness_session:
        captures = list(liveness_session.captures.all())
        liveness = {
            "expired": liveness_session.state == "expired",
            "replayed": liveness_session.state == "consumed" and liveness_session.consumed_at is None,
            "actions_completed": len(liveness_session.completed_actions) == len(liveness_session.actions),
            "anti_spoof_status": "pass" if captures and all(item.anti_spoof_status == "pass" for item in captures) else "unavailable",
        }
    refs = {"front": str(front_artifact.pk), "back": str(back_artifact.pk), "selfie": str(selfie_artifact.pk)}
    detector_results = run_configured_detectors(
        DetectorInput(
            application=application,
            front_image=_image(front_bytes),
            back_image=_image(back_bytes),
            selfie_image=_image(selfie_bytes),
            phase1_result=phase1,
            liveness=liveness,
            artifact_refs=refs,
        )
    )
    decision = decide(detector_results)

    with transaction.atomic():
        application = KYCApplication.objects.select_for_update().get(pk=application_id)
        application.extractions.filter(source=ExtractionRevision.Source.MACHINE).delete()
        for name, value in phase1.get("extracted_fields", {}).items():
            ExtractionRevision.objects.create(
                application=application,
                field_name=name,
                raw_value=value.get("raw_value"),
                normalized_value=value.get("normalized_value"),
                evidence={"items": phase1.get("field_evidence", {}).get(name, [])},
                source=ExtractionRevision.Source.MACHINE,
            )
        application.checks.all().delete()
        for item in detector_results:
            score = item.get("score") or {}
            CheckResult.objects.create(
                application=application,
                detector_name=item["detector"],
                execution_status=item["execution_status"],
                check_status=item["status"],
                score=score.get("value"),
                score_type=score.get("type") or "",
                threshold=item.get("threshold"),
                reason_codes=item.get("reason_codes", []),
                evidence=item.get("evidence", []),
                model_version=item.get("model_version") or "",
                detector_version=item["detector_version"],
                execution_ms=item.get("execution_ms", 0),
                experimental=item.get("experimental", False),
                policy_relevant=item.get("policy_relevant", True),
            )
        application.outcome = decision.outcome
        application.outcome_reasons = decision.reason_codes
        application.policy_version = decision.policy_version
        application.state = KYCApplication.State.COMPLETED
        application.completed_at = timezone.now()
        application.version += 1
        application.save()
        ReviewDecision.objects.create(
            application=application,
            outcome=decision.outcome,
            source=ReviewDecision.Source.AUTOMATED,
            reason_codes=decision.reason_codes,
            evidence_snapshot={"check_ids": list(application.checks.values_list("id", flat=True))},
            policy_version=decision.policy_version,
        )
        ProcessingJob.objects.filter(application=application).update(state=ProcessingJob.State.COMPLETED, error_code="", heartbeat_at=timezone.now())
    from .webhooks import create_event
    create_event(
        application.organization,
        "application.completed",
        {"application_id": str(application.pk), "display_id": application.display_id, "state": "completed", "outcome": decision.outcome, "policy_version": decision.policy_version},
    )
    return {"application_id": application_id, "state": "completed", "outcome": decision.outcome}


def _terminal_recapture(application_id: str, code: str, details: dict):
    reasons = details.get("recapture_reasons", [code]) if isinstance(details, dict) else [code]
    with transaction.atomic():
        application = KYCApplication.objects.select_for_update().get(pk=application_id)
        application.state = KYCApplication.State.COMPLETED
        application.outcome = KYCApplication.Outcome.NEEDS_RECAPTURE
        application.outcome_reasons = reasons
        application.completed_at = timezone.now()
        application.failure_code = ""
        application.save()
        ProcessingJob.objects.filter(application=application).update(state=ProcessingJob.State.COMPLETED, error_code="")
    return {"application_id": application_id, "state": "completed", "outcome": "needs_recapture"}


def _terminal_failure(application_id: str, code: str):
    with transaction.atomic():
        application = KYCApplication.objects.select_for_update().get(pk=application_id)
        application.state = KYCApplication.State.FAILED
        application.failure_code = code
        application.completed_at = timezone.now()
        application.save()
        ProcessingJob.objects.filter(application=application).update(state=ProcessingJob.State.FAILED, error_code=code)
    return {"application_id": application_id, "state": "failed", "error_code": code}
