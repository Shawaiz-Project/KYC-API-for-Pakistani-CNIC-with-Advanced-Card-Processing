"""Delete expired request-scoped private upload directories."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError, CommandParser

from detector.storage import cleanup_expired_request_directories


class Command(BaseCommand):
    help = "Delete expired private KYC request directories"
    # Retention must remain operable when optional OCR/detector assets are down.
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many request directories are expired without deleting them",
        )
        parser.add_argument(
            "--retention-hours",
            type=float,
            default=None,
            help="Override KYC_RETENTION_HOURS for this invocation",
        )

    def handle(self, *args: object, **options: object) -> None:
        try:
            result = cleanup_expired_request_directories(
                retention_hours=options["retention_hours"],
                dry_run=bool(options["dry_run"]),
            )
        except (OSError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        count = result.expired if options["dry_run"] else result.removed
        action = "would remove" if options["dry_run"] else "removed"
        noun = "directory" if count == 1 else "directories"
        self.stdout.write(
            f"KYC retention cleanup {action} {count} expired request {noun}; "
            f"scanned={result.scanned}, skipped={result.skipped}, failed={result.failed}."
        )
        if result.failed:
            raise CommandError(
                f"KYC retention cleanup could not remove or inspect {result.failed} request directories"
            )
