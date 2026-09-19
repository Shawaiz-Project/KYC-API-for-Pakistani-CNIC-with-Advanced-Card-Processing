from django.contrib import admin

from .models import (
    APIClientKey,
    AuditEvent,
    AuthoritativeResult,
    CheckResult,
    ConsentRecord,
    DocumentArtifact,
    DuplicateFingerprint,
    ExtractionRevision,
    KYCApplication,
    LivenessCapture,
    LivenessSession,
    Membership,
    Organization,
    ProcessingJob,
    ReviewDecision,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)


admin.site.site_header = "Shanakht review administration"
admin.site.site_title = "Shanakht"


class CheckInline(admin.TabularInline):
    model = CheckResult
    extra = 0
    can_delete = False
    readonly_fields = ("detector_name", "execution_status", "check_status", "reason_codes", "model_version", "detector_version", "execution_ms", "experimental")
    exclude = ("evidence", "score", "score_type", "threshold", "policy_relevant")


class ExtractionInline(admin.TabularInline):
    model = ExtractionRevision
    extra = 0
    can_delete = False
    readonly_fields = ("field_name", "source", "reviewer", "created_at")
    exclude = ("raw_value", "normalized_value", "confidence", "evidence", "supersedes")


@admin.register(KYCApplication)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("display_id", "organization", "state", "outcome", "workflow", "assigned_to", "created_at")
    list_filter = ("organization", "state", "outcome", "workflow")
    search_fields = ("id", "external_reference")
    readonly_fields = ("id", "policy_version", "created_at", "updated_at", "submitted_at", "processing_started_at", "completed_at")
    inlines = (CheckInline, ExtractionInline)


@admin.register(DocumentArtifact)
class ArtifactAdmin(admin.ModelAdmin):
    list_display = ("id", "application", "kind", "content_type", "byte_size", "created_at", "deleted_at")
    list_filter = ("kind", "content_type", "deleted_at")
    readonly_fields = ("storage_key", "sha256", "metadata", "created_at", "updated_at")


for model in (
    Organization,
    Membership,
    ReviewDecision,
    ConsentRecord,
    AuditEvent,
    ProcessingJob,
    LivenessSession,
    LivenessCapture,
    DuplicateFingerprint,
    APIClientKey,
    WebhookEndpoint,
    WebhookEvent,
    WebhookDelivery,
    AuthoritativeResult,
):
    admin.site.register(model)
