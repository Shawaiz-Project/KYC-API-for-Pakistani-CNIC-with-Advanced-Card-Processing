from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from detector.models import AuditEvent, DocumentArtifact
from detector.object_storage import get_object_store


class Command(BaseCommand):
    help = "Delete expired private objects and their derived fingerprints/captures."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options):
        queryset = DocumentArtifact.objects.filter(deleted_at__isnull=True, expires_at__lte=timezone.now()).select_related("application", "application__organization")[: max(1, options["limit"])]
        items = list(queryset)
        if options["dry_run"]:
            self.stdout.write(f"Would delete {len(items)} expired private objects.")
            return
        store = get_object_store()
        removed = failed = 0
        for artifact in items:
            try:
                store.delete(artifact.storage_key)
                with transaction.atomic():
                    artifact.duplicatefingerprint_set.all().delete()
                    artifact.liveness_captures.all().delete()
                    artifact.deleted_at = timezone.now()
                    artifact.storage_key = f"deleted:{artifact.pk}"
                    artifact.sha256 = ""
                    artifact.byte_size = 0
                    artifact.width = None
                    artifact.height = None
                    artifact.metadata = {}
                    artifact.save(update_fields=("deleted_at", "storage_key", "sha256", "byte_size", "width", "height", "metadata", "updated_at"))
                    if not artifact.application.artifacts.filter(deleted_at__isnull=True).exclude(pk=artifact.pk).exists():
                        artifact.application.extractions.all().delete()
                        artifact.application.fingerprints.all().delete()
                        artifact.application.liveness_sessions.all().delete()
                    AuditEvent.objects.create(organization=artifact.application.organization, application=artifact.application, event_type="artifact_retention_deleted", safe_details={"kind": artifact.kind})
                removed += 1
            except OSError:
                failed += 1
        self.stdout.write(f"Expired objects removed={removed} failed={failed}")
