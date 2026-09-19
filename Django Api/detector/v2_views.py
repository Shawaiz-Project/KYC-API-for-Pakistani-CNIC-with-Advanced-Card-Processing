from __future__ import annotations

import csv
import secrets
import uuid
from io import StringIO

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count
from django.db.models import Q
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import extend_schema
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .application_service import save_artifact
from .authentication import OrganizationAPIKeyAuthentication, issue_organization_api_key
from .errors import KYCError
from .liveness import anti_spoof_status, create_session, landmark_action_status, validate_challenge
from .models import (
    AuditEvent,
    APIClientKey,
    CheckResult,
    ConsentRecord,
    DocumentArtifact,
    ExtractionRevision,
    KYCApplication,
    LivenessCapture,
    LivenessSession,
    Membership,
    Organization,
    ProcessingJob,
    ReviewDecision,
    WebhookEndpoint,
)
from .object_storage import get_object_store
from .openapi import KYCAPIView
from .tasks import process_application_task
from .tenancy import request_membership, request_organization, require_role, require_scope
from .webhooks import UnsafeWebhookURL, encrypt_secret, new_webhook_secret, validate_webhook_url


V2_AUTH = [SessionAuthentication, OrganizationAPIKeyAuthentication]


def _boolean(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _application_queryset(request):
    organization = request_organization(request)
    queryset = KYCApplication.objects.filter(organization=organization).select_related("applicant", "assigned_to")
    membership = request_membership(request, organization)
    if membership and membership.role == Membership.Role.APPLICANT:
        queryset = queryset.filter(applicant=request.user)
    return queryset


def _application(request, pk):
    try:
        return _application_queryset(request).get(pk=pk)
    except KYCApplication.DoesNotExist as exc:
        raise KYCError("application_not_found", "The application was not found.", status.HTTP_404_NOT_FOUND) from exc


def _artifact_payload(item: DocumentArtifact) -> dict:
    return {
        "id": str(item.pk),
        "kind": item.kind,
        "content_type": item.content_type,
        "byte_size": item.byte_size,
        "dimensions": {"width": item.width, "height": item.height},
        "created_at": item.created_at.isoformat(),
        "media_url": f"/api/v2/media/{item.pk}",
    }


def _application_payload(application, *, detail: bool = False) -> dict:
    payload = {
        "id": str(application.pk),
        "display_id": application.display_id,
        "external_reference": application.external_reference,
        "state": application.state,
        "outcome": application.outcome,
        "outcome_reasons": application.outcome_reasons,
        "workflow": application.workflow,
        "policy_version": application.policy_version,
        "version": application.version,
        "submitted_at": application.submitted_at.isoformat() if application.submitted_at else None,
        "created_at": application.created_at.isoformat(),
        "completed_at": application.completed_at.isoformat() if application.completed_at else None,
        "assigned_to": application.assigned_to.username if application.assigned_to else None,
    }
    if detail:
        latest = {}
        for item in application.extractions.select_related("reviewer").order_by("field_name", "created_at"):
            entry = latest.setdefault(item.field_name, {"raw": None, "current": None, "history": []})
            if item.source == ExtractionRevision.Source.MACHINE and entry["raw"] is None:
                entry["raw"] = {"value": item.raw_value, "normalized_value": item.normalized_value, "evidence": item.evidence}
            entry["current"] = {"value": item.normalized_value, "source": item.source, "revision_id": item.pk}
            entry["history"].append({"revision_id": item.pk, "source": item.source, "created_at": item.created_at.isoformat()})
        payload.update(
            artifacts=[_artifact_payload(item) for item in application.artifacts.filter(deleted_at__isnull=True)],
            fields=latest,
            checks=[
                {
                    "detector": item.detector_name,
                    "execution_status": item.execution_status,
                    "status": item.check_status,
                    "score": None if item.score is None else {"value": item.score, "type": item.score_type, "calibrated_probability": False},
                    "threshold": item.threshold,
                    "reason_codes": item.reason_codes,
                    "evidence": item.evidence,
                    "model_version": item.model_version or None,
                    "detector_version": item.detector_version,
                    "execution_ms": item.execution_ms,
                    "experimental": item.experimental,
                }
                for item in application.checks.all()
            ],
            decisions=[
                {"outcome": item.outcome, "source": item.source, "reason_codes": item.reason_codes, "policy_version": item.policy_version, "created_at": item.created_at.isoformat()}
                for item in application.decisions.all()
            ],
            authoritative_verification={"status": "unavailable", "reason_code": "authorized_provider_not_configured"},
        )
    return payload


class CSRFView(KYCAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"csrf_token": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class SignInView(KYCAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        identifier = str(request.data.get("email") or request.data.get("username") or "").strip()
        password = str(request.data.get("password") or "")
        username = identifier
        if "@" in identifier:
            match = get_user_model().objects.filter(email__iexact=identifier, is_active=True).only("username").first()
            username = match.username if match else identifier
        user = authenticate(request, username=username, password=password)
        if user is None:
            raise KYCError("invalid_credentials", "The supplied credentials are invalid.", status.HTTP_401_UNAUTHORIZED)
        login(request, user)
        return Response(_me_payload(user))


class SignOutView(KYCAPIView):
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(KYCAPIView):
    authentication_classes = V2_AUTH

    def get(self, request):
        if hasattr(request.user, "scopes"):
            return Response({"type": "api_client", "organization_id": str(request.user.organization_id), "scopes": request.user.scopes})
        return Response(_me_payload(request.user))


def _me_payload(user) -> dict:
    memberships = user.kyc_memberships.filter(is_active=True).select_related("organization")
    return {
        "type": "user",
        "id": user.pk,
        "username": user.username,
        "email": user.email,
        "memberships": [{"organization_id": str(item.organization_id), "organization": item.organization.name, "role": item.role} for item in memberships],
    }


class ApplicationsView(KYCAPIView):
    authentication_classes = V2_AUTH
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(operation_id="v2_application_list", summary="List organization-scoped KYC applications")
    def get(self, request):
        require_scope(request, "applications:read")
        queryset = _application_queryset(request)
        if request.query_params.get("state"):
            queryset = queryset.filter(state=request.query_params["state"])
        if request.query_params.get("outcome"):
            queryset = queryset.filter(outcome=request.query_params["outcome"])
        query = request.query_params.get("q", "").strip()
        if query:
            criteria = Q(external_reference__icontains=query)
            try:
                criteria |= Q(pk=uuid.UUID(query))
            except (ValueError, TypeError):
                pass
            queryset = queryset.filter(criteria)
        limit = min(max(int(request.query_params.get("limit", 50)), 1), 100)
        items = list(queryset[:limit])
        return Response({"count": queryset.count(), "results": [_application_payload(item) for item in items]})

    def post(self, request):
        require_scope(request, "applications:write")
        organization = request_organization(request)
        idempotency_key = request.headers.get("Idempotency-Key", "").strip()
        if idempotency_key:
            existing = KYCApplication.objects.filter(organization=organization, idempotency_key=idempotency_key).first()
            if existing:
                payload = _application_payload(existing, detail=True)
                payload["idempotent_replay"] = True
                return Response(payload)
        with transaction.atomic():
            try:
                application = KYCApplication.objects.create(
                    organization=organization,
                    applicant=request.user if getattr(request.user, "pk", None) else None,
                    external_reference=str(request.data.get("external_reference", ""))[:160],
                    workflow=str(request.data.get("workflow", "cnic_standard"))[:80],
                    idempotency_key=idempotency_key,
                    policy_version=settings.KYC_POLICY_VERSION,
                )
            except IntegrityError:
                application = KYCApplication.objects.get(organization=organization, idempotency_key=idempotency_key)
                return Response(_application_payload(application, detail=True))
            AuditEvent.objects.create(organization=organization, application=application, actor=application.applicant, event_type="application_created", request_id=request.request_id)
        for kind in ("front", "back", "selfie"):
            upload = request.FILES.get(kind)
            if upload:
                save_artifact(application, kind, upload, request.request_id)
        if "consent" in request.data:
            ConsentRecord.objects.create(
                application=application,
                user=application.applicant,
                accepted=_boolean(request.data.get("consent")),
                policy_version=str(request.data.get("consent_policy_version", "phase3-consent-v1")),
            )
        if _boolean(request.data.get("auto_submit", False)):
            _submit(application, request)
            application.refresh_from_db()
        return Response(_application_payload(application, detail=True), status=status.HTTP_201_CREATED)


class ApplicationDetailView(KYCAPIView):
    authentication_classes = V2_AUTH

    @extend_schema(operation_id="v2_application_retrieve", summary="Retrieve one authorized application with evidence")
    def get(self, request, pk):
        require_scope(request, "applications:read")
        return Response(_application_payload(_application(request, pk), detail=True))


class ArtifactUploadView(KYCAPIView):
    authentication_classes = V2_AUTH
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        require_scope(request, "applications:write")
        application = _application(request, pk)
        if application.state not in {KYCApplication.State.DRAFT, KYCApplication.State.COMPLETED}:
            raise KYCError("application_not_editable", "Artifacts cannot be changed while processing.", status.HTTP_409_CONFLICT)
        kind = str(request.data.get("kind", ""))
        if kind not in {"front", "back", "selfie"}:
            raise KYCError("invalid_artifact_kind", "Artifact kind must be front, back, or selfie.")
        upload = request.FILES.get("file")
        if not upload:
            raise KYCError("missing_upload", "The file field is required.")
        artifact, validated, signals = save_artifact(application, kind, upload, request.request_id)
        
        extracted_fields = {}
        if kind in {"front", "back"}:
            try:
                from .extraction_service import auto_extract_and_store
                extracted_fields = auto_extract_and_store(application, kind, validated)
            except Exception:
                pass

        return Response(
            {
                "artifact": _artifact_payload(artifact),
                "duplicate_signals": signals,
                "extracted_fields": extracted_fields,
            },
            status=status.HTTP_201_CREATED,
        )


class CNICAutoDetectView(KYCAPIView):
    """Auto-detect all details from a CNIC card image and persist to the database."""

    authentication_classes = V2_AUTH
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload = request.FILES.get("file") or request.FILES.get("image") or request.FILES.get("front")
        if not upload:
            raise KYCError("missing_upload", "An image file is required under 'file', 'image', or 'front'.")

        organization = None
        if hasattr(request, "user") and request.user.is_authenticated:
            try:
                from .tenancy import request_organization
                organization = request_organization(request)
            except Exception:
                organization = getattr(request.user, "organization", None)

        from .extraction_service import detect_and_store_single_image
        result = detect_and_store_single_image(
            upload,
            side=str(request.data.get("side", "auto")),
            organization=organization,
            user=request.user if getattr(request.user, "is_authenticated", False) else None,
            external_reference=str(request.data.get("external_reference", "")),
        )
        return Response(result, status=status.HTTP_201_CREATED)


class SubmitApplicationView(KYCAPIView):
    authentication_classes = V2_AUTH
    parser_classes = [JSONParser, FormParser]

    def post(self, request, pk):
        require_scope(request, "applications:write")
        application = _application(request, pk)
        _submit(application, request)
        application.refresh_from_db()
        return Response(_application_payload(application, detail=True), status=status.HTTP_202_ACCEPTED)


class ConsentView(KYCAPIView):
    authentication_classes = V2_AUTH
    parser_classes = [JSONParser]

    def post(self, request, pk):
        application = _application(request, pk)
        accepted = _boolean(request.data.get("accepted"))
        record = ConsentRecord.objects.create(
            application=application,
            user=request.user if getattr(request.user, "pk", None) else None,
            accepted=accepted,
            policy_version=str(request.data.get("policy_version", "phase3-consent-v1"))[:80],
            evidence={"channel": "applicant_web"},
        )
        AuditEvent.objects.create(organization=application.organization, application=application, actor=record.user, event_type="consent_recorded", safe_details={"accepted": accepted, "scope": record.scope}, request_id=request.request_id)
        return Response({"accepted": accepted, "policy_version": record.policy_version}, status=status.HTTP_201_CREATED)


def _submit(application, request):
    kinds = set(application.artifacts.filter(deleted_at__isnull=True).values_list("kind", flat=True))
    missing = sorted({"front", "back", "selfie"} - kinds)
    if missing:
        raise KYCError("required_artifact_missing", "Front, back, and selfie artifacts are required.", details={"missing": missing})
    consent = application.consents.order_by("-created_at").first()
    if not consent or not consent.accepted:
        raise KYCError("biometric_consent_required", "Explicit document and biometric processing consent is required.", status.HTTP_422_UNPROCESSABLE_ENTITY)
    with transaction.atomic():
        locked = KYCApplication.objects.select_for_update().get(pk=application.pk)
        if locked.state in {KYCApplication.State.QUEUED, KYCApplication.State.PROCESSING}:
            return
        locked.state = KYCApplication.State.QUEUED
        locked.outcome = KYCApplication.Outcome.PENDING
        locked.submitted_at = timezone.now()
        locked.failure_code = ""
        locked.save()
        ProcessingJob.objects.update_or_create(application=locked, defaults={"state": ProcessingJob.State.QUEUED, "error_code": ""})
        AuditEvent.objects.create(organization=locked.organization, application=locked, actor=locked.applicant, event_type="application_submitted", request_id=request.request_id)
    result = process_application_task.delay(str(application.pk))
    ProcessingJob.objects.filter(application=application).update(task_id=result.id or "")


class BatchApplicationsView(KYCAPIView):
    authentication_classes = V2_AUTH
    parser_classes = [JSONParser]

    def post(self, request):
        require_scope(request, "applications:write")
        items = request.data.get("items")
        if not isinstance(items, list) or not items or len(items) > settings.KYC_MAX_BATCH_SIZE:
            raise KYCError("invalid_batch", "items must be a non-empty list within the configured batch limit.", details={"maximum": settings.KYC_MAX_BATCH_SIZE})
        organization = request_organization(request)
        results = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                results.append({"index": index, "status": "failed", "error": "invalid_item"})
                continue
            application = KYCApplication.objects.create(organization=organization, applicant=request.user if getattr(request.user, "pk", None) else None, external_reference=str(item.get("external_reference", ""))[:160])
            results.append({"index": index, "status": "created", "application": _application_payload(application)})
        return Response({"results": results}, status=status.HTTP_207_MULTI_STATUS)


class LivenessSessionsView(KYCAPIView):
    authentication_classes = V2_AUTH

    def post(self, request, pk):
        application = _application(request, pk)
        session, token = create_session(application, request.user)
        return Response({"id": str(session.pk), "actions": session.actions, "expires_at": session.expires_at.isoformat(), "challenge_token": token, "notice": "Action tracking is not anti-spoofing. Production passage also requires a separately evaluated anti-spoof model."}, status=status.HTTP_201_CREATED)


class LivenessCaptureView(KYCAPIView):
    authentication_classes = V2_AUTH
    parser_classes = [MultiPartParser]

    def post(self, request, session_id):
        try:
            session = LivenessSession.objects.select_related("application", "application__organization").get(pk=session_id, application__in=_application_queryset(request))
        except LivenessSession.DoesNotExist as exc:
            raise KYCError("liveness_session_not_found", "The liveness session was not found.", status.HTTP_404_NOT_FOUND) from exc
        validate_challenge(session, str(request.data.get("challenge_token", "")))
        action = str(request.data.get("action", ""))
        next_index = len(session.completed_actions)
        if next_index >= len(session.actions) or action != session.actions[next_index]:
            raise KYCError("unexpected_liveness_action", "The submitted action is not the current challenge.", status.HTTP_409_CONFLICT)
        upload = request.FILES.get("file")
        if not upload:
            raise KYCError("missing_upload", "The file field is required.")
        artifact, validated, _ = save_artifact(session.application, "liveness", upload, request.request_id)
        tracker, evidence = landmark_action_status(validated.bgr_image, action)
        spoof, model = anti_spoof_status(validated.bgr_image)
        LivenessCapture.objects.create(session=session, action=action, artifact=artifact, landmark_evidence=evidence, tracker_status=tracker, anti_spoof_status=spoof)
        if tracker == "pass":
            session.completed_actions = [*session.completed_actions, action]
            session.save(update_fields=("completed_actions", "updated_at"))
        return Response({"action": action, "tracker_status": tracker, "anti_spoof_status": spoof, "anti_spoof_model": model, "evidence": evidence})


class LivenessCompleteView(KYCAPIView):
    authentication_classes = V2_AUTH
    parser_classes = [JSONParser]

    def post(self, request, session_id):
        try:
            session = LivenessSession.objects.select_related("application").get(pk=session_id, application__in=_application_queryset(request))
        except LivenessSession.DoesNotExist as exc:
            raise KYCError("liveness_session_not_found", "The liveness session was not found.", status.HTTP_404_NOT_FOUND) from exc
        validate_challenge(session, str(request.data.get("challenge_token", "")))
        if _boolean(request.data.get("manual_review")):
            session.alternative_requested = True
            session.state = LivenessSession.State.REVIEW
        elif len(session.completed_actions) != len(session.actions):
            raise KYCError("liveness_incomplete", "Not all liveness actions were validated. A manual-review alternative is available.", status.HTTP_422_UNPROCESSABLE_ENTITY)
        else:
            session.state = LivenessSession.State.CONSUMED
        session.consumed_at = timezone.now()
        session.save(update_fields=("state", "alternative_requested", "consumed_at", "updated_at"))
        return Response({"state": session.state, "manual_review": session.alternative_requested})


class MediaView(KYCAPIView):
    authentication_classes = V2_AUTH

    def get(self, request, artifact_id):
        try:
            artifact = DocumentArtifact.objects.select_related("application").get(pk=artifact_id, application__in=_application_queryset(request), deleted_at__isnull=True)
        except DocumentArtifact.DoesNotExist as exc:
            raise KYCError("media_not_found", "The media object was not found.", status.HTTP_404_NOT_FOUND) from exc
        response = HttpResponse(get_object_store().get(artifact.storage_key), content_type=artifact.content_type)
        response["Content-Disposition"] = f'inline; filename="{artifact.kind}-{artifact.pk}.bin"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class CorrectFieldView(KYCAPIView):
    authentication_classes = V2_AUTH
    parser_classes = [JSONParser]

    def post(self, request, pk):
        require_role(request, Membership.Role.ADMIN, Membership.Role.REVIEWER)
        application = _application(request, pk)
        field_name = str(request.data.get("field_name", "")).strip()
        value = request.data.get("value")
        reason = str(request.data.get("reason", "")).strip()
        if not field_name or value is None or not reason:
            raise KYCError("invalid_correction", "field_name, value, and reason are required.")
        prior = application.extractions.filter(field_name=field_name).order_by("-created_at").first()
        correction = ExtractionRevision.objects.create(application=application, field_name=field_name, raw_value=None, normalized_value=str(value), evidence={"reason": reason}, source=ExtractionRevision.Source.REVIEWER, reviewer=request.user, supersedes=prior)
        AuditEvent.objects.create(organization=application.organization, application=application, actor=request.user, event_type="ocr_corrected", safe_details={"field_name": field_name, "revision_id": correction.pk}, request_id=request.request_id)
        return Response({"revision_id": correction.pk, "field_name": field_name, "value": correction.normalized_value}, status=status.HTTP_201_CREATED)


class ReviewDecisionView(KYCAPIView):
    authentication_classes = V2_AUTH
    parser_classes = [JSONParser]

    def post(self, request, pk):
        require_role(request, Membership.Role.ADMIN, Membership.Role.REVIEWER)
        application = _application(request, pk)
        outcome = str(request.data.get("outcome", ""))
        reason = str(request.data.get("reason", "")).strip()
        if outcome not in KYCApplication.Outcome.values or outcome == KYCApplication.Outcome.PENDING or not reason:
            raise KYCError("invalid_review_decision", "A supported non-pending outcome and reason are required.")
        snapshot = {"check_ids": list(application.checks.values_list("id", flat=True)), "extraction_revision_ids": list(application.extractions.values_list("id", flat=True)), "application_version": application.version}
        decision = ReviewDecision.objects.create(application=application, outcome=outcome, source=ReviewDecision.Source.REVIEWER, reviewer=request.user, reason_codes=[reason], notes=str(request.data.get("notes", "")), evidence_snapshot=snapshot, policy_version=application.policy_version)
        application.outcome = outcome
        application.outcome_reasons = [reason]
        application.version += 1
        application.save(update_fields=("outcome", "outcome_reasons", "version", "updated_at"))
        AuditEvent.objects.create(organization=application.organization, application=application, actor=request.user, event_type="review_decision_recorded", safe_details={"decision_id": decision.pk, "outcome": outcome}, request_id=request.request_id)
        return Response({"decision_id": decision.pk, "outcome": outcome}, status=status.HTTP_201_CREATED)


class AssignmentView(KYCAPIView):
    authentication_classes = V2_AUTH
    parser_classes = [JSONParser]

    def post(self, request, pk):
        require_role(request, Membership.Role.ADMIN, Membership.Role.REVIEWER)
        application = _application(request, pk)
        username = str(request.data.get("username", "")).strip()
        membership = Membership.objects.filter(
            organization=application.organization,
            user__username=username,
            role__in=(Membership.Role.ADMIN, Membership.Role.REVIEWER),
            is_active=True,
        ).select_related("user").first()
        if membership is None:
            raise KYCError("reviewer_not_found", "An active reviewer in this organization was not found.", status.HTTP_404_NOT_FOUND)
        application.assigned_to = membership.user
        application.version += 1
        application.save(update_fields=("assigned_to", "version", "updated_at"))
        AuditEvent.objects.create(organization=application.organization, application=application, actor=request.user, event_type="reviewer_assigned", safe_details={"reviewer_user_id": membership.user_id}, request_id=request.request_id)
        return Response({"assigned_to": membership.user.username, "version": application.version})


class OverviewView(KYCAPIView):
    authentication_classes = V2_AUTH

    def get(self, request):
        require_role(request, Membership.Role.ADMIN, Membership.Role.REVIEWER)
        queryset = _application_queryset(request)
        return Response({
            "total": queryset.count(),
            "queued": queryset.filter(state=KYCApplication.State.QUEUED).count(),
            "processing": queryset.filter(state=KYCApplication.State.PROCESSING).count(),
            "completed": queryset.filter(state=KYCApplication.State.COMPLETED).count(),
            "failed": queryset.filter(state=KYCApplication.State.FAILED).count(),
            "needs_review": queryset.filter(outcome=KYCApplication.Outcome.NEEDS_REVIEW).count(),
            "needs_recapture": queryset.filter(outcome=KYCApplication.Outcome.NEEDS_RECAPTURE).count(),
        })


class ExportView(KYCAPIView):
    authentication_classes = V2_AUTH

    def get(self, request):
        require_role(request, Membership.Role.ADMIN, Membership.Role.REVIEWER)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(("application_id", "state", "outcome", "submitted_at", "policy_version"))
        for item in _application_queryset(request):
            writer.writerow((item.display_id, item.state, item.outcome, item.submitted_at.isoformat() if item.submitted_at else "", item.policy_version))
        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="applications.csv"'
        response["Cache-Control"] = "private, no-store"
        return response


class WebhookEndpointsView(KYCAPIView):
    authentication_classes = V2_AUTH
    parser_classes = [JSONParser]

    def get(self, request):
        require_role(request, Membership.Role.ADMIN)
        organization = request_organization(request)
        return Response({"results": [{"id": item.pk, "url": item.url, "event_types": item.event_types, "is_active": item.is_active, "created_at": item.created_at.isoformat()} for item in organization.webhook_endpoints.all()]})

    def post(self, request):
        require_role(request, Membership.Role.ADMIN)
        organization = request_organization(request)
        url = str(request.data.get("url", ""))
        event_types = request.data.get("event_types", ["application.completed"])
        if not isinstance(event_types, list) or not all(isinstance(item, str) for item in event_types):
            raise KYCError("invalid_webhook_events", "event_types must be a list of event names.")
        try:
            validate_webhook_url(url)
            secret = new_webhook_secret()
            ciphertext = encrypt_secret(secret)
        except UnsafeWebhookURL as exc:
            raise KYCError("unsafe_webhook_destination", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
        except RuntimeError as exc:
            raise KYCError("webhook_encryption_unavailable", str(exc), status.HTTP_503_SERVICE_UNAVAILABLE) from exc
        endpoint = WebhookEndpoint.objects.create(organization=organization, url=url, event_types=event_types, secret_ciphertext=ciphertext)
        return Response({"id": endpoint.pk, "url": endpoint.url, "event_types": endpoint.event_types, "secret": secret, "notice": "The signing secret is returned once. Store it securely."}, status=status.HTTP_201_CREATED)


class WebhookDeliveriesView(KYCAPIView):
    authentication_classes = V2_AUTH

    def get(self, request, endpoint_id):
        require_role(request, Membership.Role.ADMIN)
        organization = request_organization(request)
        try:
            endpoint = organization.webhook_endpoints.get(pk=endpoint_id)
        except WebhookEndpoint.DoesNotExist as exc:
            raise KYCError("webhook_not_found", "The webhook endpoint was not found.", status.HTTP_404_NOT_FOUND) from exc
        return Response({"results": [{"event_id": str(item.event_id), "state": item.state, "attempts": item.attempts, "response_status": item.response_status, "error_code": item.error_code, "updated_at": item.updated_at.isoformat()} for item in endpoint.deliveries.select_related("event").all()[:100]]})


class MetricsView(KYCAPIView):
    authentication_classes = V2_AUTH

    def get(self, request):
        require_role(request, Membership.Role.ADMIN)
        organization = request_organization(request)
        applications = KYCApplication.objects.filter(organization=organization)
        checks = CheckResult.objects.filter(application__organization=organization)
        lines = [
            "# HELP shanakht_applications Current application count by state.",
            "# TYPE shanakht_applications gauge",
        ]
        for value in KYCApplication.State.values:
            lines.append(f'shanakht_applications{{state="{value}"}} {applications.filter(state=value).count()}')
        lines.extend(("# HELP shanakht_check_execution_ms Average detector execution milliseconds.", "# TYPE shanakht_check_execution_ms gauge"))
        for item in checks.values("detector_name", "model_version").annotate(value=Avg("execution_ms")):
            detector = item["detector_name"].replace('"', "")
            model = (item["model_version"] or "none").replace('"', "")
            lines.append(f'shanakht_check_execution_ms{{detector="{detector}",model="{model}"}} {item["value"] or 0}')
        lines.extend(("# HELP shanakht_check_results Detector results by execution status.", "# TYPE shanakht_check_results gauge"))
        for item in checks.values("detector_name", "execution_status", "model_version").annotate(value=Count("id")):
            detector = item["detector_name"].replace('"', "")
            model = (item["model_version"] or "none").replace('"', "")
            execution_status = item["execution_status"].replace('"', "")
            lines.append(f'shanakht_check_results{{detector="{detector}",model="{model}",status="{execution_status}"}} {item["value"]}')
        lines.extend(("# HELP shanakht_recapture_total Applications requiring recapture.", "# TYPE shanakht_recapture_total gauge", f"shanakht_recapture_total {applications.filter(outcome=KYCApplication.Outcome.NEEDS_RECAPTURE).count()}"))
        lines.extend(("# HELP shanakht_queue_depth Queued and running application jobs.", "# TYPE shanakht_queue_depth gauge", f"shanakht_queue_depth {applications.filter(state__in=[KYCApplication.State.QUEUED, KYCApplication.State.PROCESSING]).count()}"))
        lines.extend(("# HELP shanakht_reviewer_corrections_total Reviewer OCR correction revisions.", "# TYPE shanakht_reviewer_corrections_total gauge", f"shanakht_reviewer_corrections_total {ExtractionRevision.objects.filter(application__organization=organization, source=ExtractionRevision.Source.REVIEWER).count()}"))
        response = HttpResponse("\n".join(lines) + "\n", content_type="text/plain; version=0.0.4")
        response["Cache-Control"] = "private, no-store"
        return response


class APIKeysView(KYCAPIView):
    authentication_classes = [SessionAuthentication]
    parser_classes = [JSONParser]

    def get(self, request):
        require_role(request, Membership.Role.ADMIN)
        organization = request_organization(request)
        return Response({"results": [{"id": item.pk, "name": item.name, "prefix": item.prefix, "scopes": item.scopes, "is_active": item.is_active, "quota_per_minute": item.quota_per_minute, "usage_count": item.usage_count, "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None, "created_at": item.created_at.isoformat()} for item in organization.api_keys.all()]})

    def post(self, request):
        require_role(request, Membership.Role.ADMIN)
        organization = request_organization(request)
        scopes = request.data.get("scopes", ["applications:read", "applications:write"])
        allowed = {"applications:read", "applications:write", "*"}
        if not isinstance(scopes, list) or not scopes or not set(scopes) <= allowed:
            raise KYCError("invalid_api_key_scopes", "The requested API key scopes are invalid.")
        record, plaintext = issue_organization_api_key(organization, str(request.data.get("name", "API client"))[:120], scopes, int(request.data.get("quota_per_minute", 30)))
        AuditEvent.objects.create(organization=organization, actor=request.user, event_type="api_key_created", safe_details={"api_key_id": record.pk, "scopes": scopes}, request_id=request.request_id)
        return Response({"id": record.pk, "prefix": record.prefix, "api_key": plaintext, "scopes": scopes, "notice": "The plaintext API key is returned once."}, status=status.HTTP_201_CREATED)


class APIKeyActionView(KYCAPIView):
    authentication_classes = [SessionAuthentication]
    parser_classes = [JSONParser]

    def post(self, request, key_id):
        require_role(request, Membership.Role.ADMIN)
        organization = request_organization(request)
        try:
            old = organization.api_keys.get(pk=key_id)
        except APIClientKey.DoesNotExist as exc:
            raise KYCError("api_key_not_found", "The API key was not found.", status.HTTP_404_NOT_FOUND) from exc
        action = request.data.get("action")
        if action not in {"revoke", "rotate"}:
            raise KYCError("invalid_api_key_action", "action must be revoke or rotate.")
        old.is_active = False
        old.revoked_at = timezone.now()
        old.save(update_fields=("is_active", "revoked_at", "updated_at"))
        payload = {"revoked": True, "id": old.pk}
        if action == "rotate":
            replacement, plaintext = issue_organization_api_key(organization, f"{old.name} rotated"[:120], list(old.scopes), old.quota_per_minute)
            payload.update({"replacement_id": replacement.pk, "api_key": plaintext, "notice": "The replacement plaintext is returned once."})
        AuditEvent.objects.create(organization=organization, actor=request.user, event_type=f"api_key_{action}", safe_details={"api_key_id": old.pk, "replacement_id": payload.get("replacement_id")}, request_id=request.request_id)
        return Response(payload)
