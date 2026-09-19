from pathlib import Path

from django.core.management.base import BaseCommand

from detector.phase2_evaluation import evaluate_manifest, write_result


class Command(BaseCommand):
    help = "Evaluate Phase 2 predictions with identity-group split validation and uncertainty intervals."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", default="evaluation-data/phase2-results.csv")
        parser.add_argument("--output", default="benchmarks/phase2-result.json")

    def handle(self, *args, **options):
        result = evaluate_manifest(Path(options["manifest"]))
        write_result(result, Path(options["output"]))
        self.stdout.write(f"Phase 2 evaluation status={result['status']} output={options['output']}")
