from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError, CommandParser

from detector.model_registry import ModelUnavailableError, get_model_registry, reset_model_registry


class Command(BaseCommand):
    help = "Load and optionally acquire the configured EasyOCR models"
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--allow-download",
            action="store_true",
            help="Explicitly allow EasyOCR to download its upstream model assets",
        )

    def handle(self, *args: object, **options: object) -> None:
        reset_model_registry()
        try:
            reader = get_model_registry().get_ocr_reader(
                allow_download=bool(options["allow_download"])
            )
        except ModelUnavailableError as exc:
            raise CommandError(
                f"OCR model warm-up failed: {exc.details.get('reason', 'unavailable')}"
            ) from exc
        if reader is None:
            raise CommandError("OCR is disabled")
        self.stdout.write(
            self.style.SUCCESS(
                "EasyOCR models loaded successfully. Run model_manifest to record SHA-256 values."
            )
        )

