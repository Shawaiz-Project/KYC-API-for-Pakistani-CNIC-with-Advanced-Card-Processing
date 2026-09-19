"""Durable, tenant-scoped state for Phase 2 and Phase 3 workflows.

Sensitive binary data is referenced by an opaque private-storage key. It is
never exposed through Django's public media machinery.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Organization(TimeStampedModel):
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=80, unique=True)
    retention_hours = models.PositiveIntegerField(default=24)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class Membership(TimeStampedModel):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        REVIEWER = "reviewer", "Reviewer"
        APPLICANT = "applicant", "Applicant"
        API_CLIENT = "api_client", "API client"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="kyc_memberships")
    role = models.CharField(max_length=24, choices=Role.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("organization", "user", "role"), name="unique_organization_user_role")]


class KYCApplication(TimeStampedModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Outcome(models.TextChoices):
        PENDING = "pending", "Pending"
        CHECKS_PASSED = "checks_passed", "Checks passed"
        CHECKS_FAILED = "checks_failed", "Checks failed"
        NEEDS_RECAPTURE = "needs_recapture", "Needs recapture"
        NEEDS_REVIEW = "needs_review", "Needs review"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="applications")
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="kyc_applications")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_kyc_applications")
    external_reference = models.CharField(max_length=160, blank=True)
    workflow = models.CharField(max_length=80, default="cnic_standard")
    policy_version = models.CharField(max_length=80, default="phase2-policy-v1")
    state = models.CharField(max_length=24, choices=State.choices, default=State.DRAFT)
    outcome = models.CharField(max_length=24, choices=Outcome.choices, default=Outcome.PENDING)
    outcome_reasons = models.JSONField(default=list, blank=True)
    idempotency_key = models.CharField(max_length=160, blank=True)
    version = models.PositiveIntegerField(default=1)
    submitted_at = models.DateTimeField(null=True, blank=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [models.UniqueConstraint(fields=("organization", "idempotency_key"), condition=~models.Q(idempotency_key=""), name="unique_org_nonempty_idempotency_key")]
        indexes = [models.Index(fields=("organization", "state", "created_at")), models.Index(fields=("organization", "outcome", "created_at"))]

    @property
    def display_id(self) -> str:
        return f"APP-{str(self.pk).split('-')[0].upper()}"

    def __str__(self) -> str:
        return self.display_id


class DocumentArtifact(TimeStampedModel):
    class Kind(models.TextChoices):
        FRONT = "front", "Document front"
        BACK = "back", "Document back"
        SELFIE = "selfie", "Applicant selfie"
        LIVENESS = "liveness", "Liveness capture"
        PROCESSING = "processing", "Annotated processing copy"

    application = models.ForeignKey(KYCApplication, on_delete=models.CASCADE, related_name="artifacts")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    storage_key = models.CharField(max_length=500, unique=True)
    content_type = models.CharField(max_length=100)
    byte_size = models.PositiveBigIntegerField()
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=("application", "kind", "created_at"))]


class ExtractionRevision(TimeStampedModel):
    class Source(models.TextChoices):
        MACHINE = "machine", "Machine extraction"
        REVIEWER = "reviewer", "Reviewer correction"

    application = models.ForeignKey(KYCApplication, on_delete=models.CASCADE, related_name="extractions")
    field_name = models.CharField(max_length=80)
    raw_value = models.TextField(null=True, blank=True)
    normalized_value = models.TextField(null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=16, choices=Source.choices)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    supersedes = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="revisions")

    class Meta:
        ordering = ("field_name", "created_at")
        indexes = [models.Index(fields=("application", "field_name", "created_at"))]


class CheckResult(TimeStampedModel):
    class ExecutionStatus(models.TextChoices):
        DISABLED = "disabled", "Disabled"
        UNAVAILABLE = "unavailable", "Unavailable"
        FAILED = "failed", "Execution failed"
        COMPLETED = "completed", "Completed"

    class CheckStatus(models.TextChoices):
        PASS = "pass", "Pass"
        FAIL = "fail", "Fail"
        UNCERTAIN = "uncertain", "Uncertain"
        NOT_RUN = "not_run", "Not run"
        UNAVAILABLE = "unavailable", "Unavailable"

    application = models.ForeignKey(KYCApplication, on_delete=models.CASCADE, related_name="checks")
    detector_name = models.CharField(max_length=100)
    execution_status = models.CharField(max_length=16, choices=ExecutionStatus.choices)
    check_status = models.CharField(max_length=16, choices=CheckStatus.choices)
    score = models.FloatField(null=True, blank=True)
    score_type = models.CharField(max_length=80, blank=True)
    threshold = models.FloatField(null=True, blank=True)
    reason_codes = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    model_version = models.CharField(max_length=160, blank=True)
    detector_version = models.CharField(max_length=80)
    execution_ms = models.FloatField(default=0)
    experimental = models.BooleanField(default=False)
    policy_relevant = models.BooleanField(default=True)

    class Meta:
        ordering = ("detector_name", "created_at")
        indexes = [models.Index(fields=("application", "detector_name", "created_at"))]


class ReviewDecision(TimeStampedModel):
    class Source(models.TextChoices):
        AUTOMATED = "automated", "Policy engine"
        REVIEWER = "reviewer", "Human reviewer"

    application = models.ForeignKey(KYCApplication, on_delete=models.CASCADE, related_name="decisions")
    outcome = models.CharField(max_length=24, choices=KYCApplication.Outcome.choices)
    source = models.CharField(max_length=16, choices=Source.choices)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    reason_codes = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    evidence_snapshot = models.JSONField(default=dict, blank=True)
    policy_version = models.CharField(max_length=80)


class ConsentRecord(TimeStampedModel):
    application = models.ForeignKey(KYCApplication, on_delete=models.CASCADE, related_name="consents")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    scope = models.CharField(max_length=80, default="documents_and_biometrics")
    accepted = models.BooleanField()
    policy_version = models.CharField(max_length=80)
    evidence = models.JSONField(default=dict, blank=True)


class AuditEvent(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="audit_events")
    application = models.ForeignKey(KYCApplication, null=True, blank=True, on_delete=models.CASCADE, related_name="audit_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=100)
    safe_details = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("organization", "event_type", "created_at"))]


class ProcessingJob(TimeStampedModel):
    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    application = models.OneToOneField(KYCApplication, on_delete=models.CASCADE, related_name="job")
    state = models.CharField(max_length=16, choices=State.choices, default=State.QUEUED)
    task_id = models.CharField(max_length=160, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    error_code = models.CharField(max_length=80, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)


class LivenessSession(TimeStampedModel):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        EXPIRED = "expired", "Expired"
        CONSUMED = "consumed", "Consumed"
        REVIEW = "review", "Manual review"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(KYCApplication, on_delete=models.CASCADE, related_name="liveness_sessions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    actions = models.JSONField(default=list)
    completed_actions = models.JSONField(default=list)
    challenge_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    alternative_requested = models.BooleanField(default=False)


class LivenessCapture(TimeStampedModel):
    session = models.ForeignKey(LivenessSession, on_delete=models.CASCADE, related_name="captures")
    action = models.CharField(max_length=40)
    artifact = models.ForeignKey(DocumentArtifact, on_delete=models.PROTECT, related_name="liveness_captures")
    landmark_evidence = models.JSONField(default=dict, blank=True)
    tracker_status = models.CharField(max_length=20, default="unavailable")
    anti_spoof_status = models.CharField(max_length=20, default="unavailable")


class DuplicateFingerprint(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="fingerprints")
    application = models.ForeignKey(KYCApplication, on_delete=models.CASCADE, related_name="fingerprints")
    artifact = models.ForeignKey(DocumentArtifact, null=True, blank=True, on_delete=models.CASCADE)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    perceptual_hash = models.CharField(max_length=32, blank=True, db_index=True)
    identifier_hmac = models.CharField(max_length=64, blank=True, db_index=True)
    identifier_confidence = models.FloatField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=("organization", "sha256")), models.Index(fields=("organization", "identifier_hmac"))]


class APIClientKey(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=120)
    prefix = models.CharField(max_length=16, db_index=True)
    digest = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    quota_per_minute = models.PositiveIntegerField(default=30)
    usage_count = models.PositiveBigIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class WebhookEndpoint(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="webhook_endpoints")
    url = models.URLField(max_length=500)
    event_types = models.JSONField(default=list)
    secret_ciphertext = models.TextField()
    is_active = models.BooleanField(default=True)


class WebhookEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="webhook_events")
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class WebhookDelivery(TimeStampedModel):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    endpoint = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries")
    event = models.ForeignKey(WebhookEvent, on_delete=models.CASCADE, related_name="deliveries")
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    response_status = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("endpoint", "event"), name="unique_webhook_delivery")]


class AuthoritativeResult(TimeStampedModel):
    application = models.ForeignKey(KYCApplication, on_delete=models.CASCADE, related_name="authoritative_results")
    provider = models.CharField(max_length=100)
    status = models.CharField(max_length=20, default="unavailable")
    reason_code = models.CharField(max_length=100, default="provider_not_configured")
    reference = models.CharField(max_length=160, blank=True)
    provider_version = models.CharField(max_length=80, blank=True)
