import csv
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from .phase2_evaluation import evaluate_manifest, wilson


class Phase2EvaluationTests(SimpleTestCase):
    def test_missing_manifest_reports_exact_blockers(self):
        result = evaluate_manifest(Path("does-not-exist.csv"))
        self.assertEqual(result["status"], "not_run")
        self.assertIn("consented_representative_evaluation_data_missing", result["blockers"])

    def test_identity_group_leakage_invalidates_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=("identity_group", "split"))
                writer.writeheader()
                writer.writerows(({"identity_group": "person-1", "split": "training"}, {"identity_group": "person-1", "split": "evaluation"}))
            result = evaluate_manifest(path)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["leaking_group_count"], 1)

    def test_wilson_interval_records_sample_size_and_uncertainty(self):
        result = wilson(5, 10)
        self.assertEqual(result["rate"], 0.5)
        self.assertEqual(result["count"], 10)
        self.assertLess(result["interval_95"][0], result["rate"])
        self.assertGreater(result["interval_95"][1], result["rate"])
