"""Run the privacy-preserving Phase 1 held-out evaluation harness."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from detector.evaluation import run_benchmark


def _write_report(path: Path, report_text: str, protected_paths: set[Path]) -> None:
    resolved = path.expanduser().resolve(strict=False)
    if resolved in protected_paths:
        raise CommandError("Refusing to overwrite an evaluation input file.")
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            dir=resolved.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(report_text)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, resolved)
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except (NameError, OSError):
            pass
        raise CommandError("The benchmark report could not be written.") from exc


class Command(BaseCommand):
    help = "Benchmark the KYC pipeline on a grouped evaluation manifest"
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--manifest",
            default=None,
            help="Manifest path (defaults to benchmarks/manifest.json)",
        )
        parser.add_argument(
            "--split",
            default="held_out",
            help="Dataset split to evaluate (default: held_out)",
        )
        parser.add_argument(
            "--baseline",
            default=None,
            help="Optional prior aggregate benchmark report",
        )
        parser.add_argument(
            "--output",
            default=None,
            help="Optional path for the aggregate JSON report",
        )
        parser.add_argument(
            "--iou-threshold",
            type=float,
            default=None,
            help="Override the manifest card-detection IoU threshold",
        )
        parser.add_argument(
            "--warmup-pairs",
            type=int,
            default=1,
            help="Number of unmeasured warm-up pipeline calls (default: 1)",
        )

    def handle(self, *args: object, **options: object) -> None:
        repository_root = Path(settings.REPOSITORY_ROOT)
        manifest = self._repository_path(
            options["manifest"] or repository_root / "benchmarks" / "manifest.json",
            repository_root,
        )
        baseline = (
            self._repository_path(options["baseline"], repository_root)
            if options["baseline"]
            else None
        )
        report = run_benchmark(
            manifest,
            split=str(options["split"]),
            baseline_path=baseline,
            detection_iou_threshold=options["iou_threshold"],
            warmup_pairs=options["warmup_pairs"],
        )
        report_text = json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        if options["output"]:
            protected = {manifest.expanduser().resolve(strict=False)}
            if baseline is not None:
                protected.add(baseline.expanduser().resolve(strict=False))
            output = self._repository_path(options["output"], repository_root)
            _write_report(output, report_text, protected)
        self.stdout.write(report_text)

    @staticmethod
    def _repository_path(value: object, repository_root: Path) -> Path:
        path = Path(str(value)).expanduser()
        return path if path.is_absolute() else repository_root / path
