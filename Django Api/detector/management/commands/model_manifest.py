from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from detector.model_registry import sha256_file, weight_manifest


class Command(BaseCommand):
    help = "Emit a privacy-safe SHA-256 manifest for configured model assets"
    requires_system_checks: list[str] = []

    def handle(self, *args: object, **options: object) -> None:
        payload: dict[str, object] = {
            "schema_version": 1,
            "easyocr": {
                "languages": list(settings.KYC_OCR_LANGUAGES),
                "files": weight_manifest(Path(settings.KYC_OCR_MODEL_DIR)),
            },
            "card_detector": None,
        }
        detector = settings.KYC_CARD_DETECTOR_MODEL
        if detector:
            path = Path(detector)
            if path.is_file():
                payload["card_detector"] = {
                    "file": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            else:
                payload["card_detector"] = {"status": "unavailable", "reason": "weight_file_not_found"}
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
