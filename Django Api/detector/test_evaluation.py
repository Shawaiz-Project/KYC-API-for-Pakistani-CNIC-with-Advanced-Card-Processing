from __future__ import annotations

import copy
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase

from detector.errors import KYCError
from detector.evaluation import (
    compare_with_baseline,
    load_manifest,
    run_benchmark,
)


def grouped_pair(
    *,
    person: str,
    document: str,
    split: str,
    front_path: str,
    back_path: str,
    expected: dict | None = None,
) -> dict:
    return {
        "person_group_id": person,
        "document_group_id": document,
        "split": split,
        "front_path": front_path,
        "back_path": back_path,
        "expected": expected
        or {"fields": {}, "urdu_text": {}, "card_boxes": {}},
    }


class EvaluationHarnessTests(SimpleTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def write_manifest(self, pairs: list[dict], **extra: object) -> Path:
        path = self.root / "manifest.json"
        payload = {
            "schema_version": "1.0",
            "dataset": {"name": "synthetic-evaluation", "version": "test-v1"},
            "detection_iou_threshold": 0.5,
            "pairs": pairs,
            **extra,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def create_assets(self) -> tuple[Path, Path]:
        front = self.root / "synthetic-front.jpg"
        back = self.root / "synthetic-back.jpg"
        front.write_bytes(b"synthetic front bytes")
        back.write_bytes(b"synthetic back bytes")
        return front, back

    def test_missing_manifest_is_not_run_with_exact_blocker(self) -> None:
        report = run_benchmark(self.root / "absent.json")

        self.assertEqual(report["status"], "not_run")
        self.assertEqual(report["blockers"][0]["code"], "manifest_not_found")
        self.assertEqual(report["metrics"]["field_exact_match"]["status"], "not_run")
        self.assertNotIn("accuracy", report["metrics"]["field_exact_match"])

    def test_group_leakage_is_rejected_before_assets_or_pipeline(self) -> None:
        pairs = [
            grouped_pair(
                person="opaque-person-0001",
                document="opaque-document-0001",
                split="train",
                front_path="does-not-exist/train-front.jpg",
                back_path="does-not-exist/train-back.jpg",
            ),
            grouped_pair(
                person="opaque-person-0001",
                document="opaque-document-0001",
                split="held_out",
                front_path="does-not-exist/test-front.jpg",
                back_path="does-not-exist/test-back.jpg",
            ),
        ]

        report = run_benchmark(self.write_manifest(pairs))

        self.assertEqual(report["status"], "not_run")
        self.assertEqual(report["blockers"][0]["code"], "group_split_leakage")
        details = report["blockers"][0]["details"]
        self.assertEqual(details["person_groups_with_leakage"], 1)
        self.assertEqual(details["document_groups_with_leakage"], 1)
        serialized = json.dumps(report)
        self.assertNotIn("opaque-person-0001", serialized)
        self.assertNotIn("opaque-document-0001", serialized)

    def test_group_identifiers_are_required_to_be_opaque(self) -> None:
        pair = grouped_pair(
            person="12345-1234567-1",
            document="opaque-document-0001",
            split="held_out",
            front_path="missing-front.jpg",
            back_path="missing-back.jpg",
        )

        report = run_benchmark(self.write_manifest([pair]))

        self.assertEqual(report["status"], "not_run")
        self.assertEqual(
            report["blockers"][0]["code"], "non_opaque_person_group_id"
        )

    def test_missing_assets_are_reported_without_calling_pipeline(self) -> None:
        pair = grouped_pair(
            person="opaque-person-0001",
            document="opaque-document-0001",
            split="held_out",
            front_path="missing-front.jpg",
            back_path="missing-back.jpg",
        )

        def should_not_run(*_args: object) -> dict:
            raise AssertionError("pipeline must not run without paired assets")

        report = run_benchmark(
            self.write_manifest([pair]), processor=should_not_run
        )

        self.assertEqual(report["status"], "not_run")
        self.assertEqual(
            {blocker["code"] for blocker in report["blockers"]},
            {"front_assets_missing", "back_assets_missing"},
        )
        self.assertEqual(report["dataset"]["pair_count"], 1)

    def test_held_out_metrics_latency_memory_and_metadata_are_aggregate(self) -> None:
        front, back = self.create_assets()
        expected = {
            "fields": {
                "name": "SYNTHETIC EXAMPLE",
                "cnic_number": "00000-0000000-0",
            },
            "urdu_text": {"front": "ابج", "back": None},
            "card_boxes": {
                "front": [[0, 0, 10, 10]],
                "back": [[0, 0, 10, 10]],
            },
        }
        pair = grouped_pair(
            person="opaque-person-0001",
            document="opaque-document-0001",
            split="held_out",
            front_path=str(front),
            back_path=str(back),
            expected=expected,
        )
        manifest = self.write_manifest([pair])
        calls: list[tuple[str, str]] = []

        def fake_pipeline(front_upload, back_upload, request_id: str) -> dict:
            calls.append((front_upload.name, back_upload.name))
            self.assertRegex(request_id, r"\Abenchmark-[0-9a-f]{32}\Z")
            return {
                "fields": {
                    "name": {"normalized_value": "SYNTHETIC EXAMPLE"},
                    "cnic_number": {"normalized_value": "99999-9999999-9"},
                },
                "ocr": {
                    "engine": "synthetic-ocr",
                    "raw_detections": {
                        "front": [{"side": "front", "raw_text": "اب"}],
                        "back": [],
                    },
                },
                "document": {
                    "sides": {
                        "front": {
                            "detection": {
                                "corners": [[0, 0], [10, 0], [10, 10], [0, 10]]
                            }
                        },
                        "back": {
                            "detection": {
                                "corners": [
                                    [20, 20],
                                    [30, 20],
                                    [30, 30],
                                    [20, 30],
                                ]
                            }
                        },
                    }
                },
                "model_versions": {
                    "ocr": {
                        "name": "synthetic-ocr",
                        "version": "1",
                        "sha256": "0" * 64,
                        "device": "cpu",
                    }
                },
            }

        clock_values = iter((10.0, 10.1))
        rss_values = iter((100, 120, 140))
        report = run_benchmark(
            manifest,
            processor=fake_pipeline,
            clock=lambda: next(clock_values),
            rss_reader=lambda: next(rss_values),
        )

        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(calls), 2)  # one warm-up plus one measured pair
        self.assertEqual(calls[0], ("front-benchmark.jpg", "back-benchmark.jpg"))

        field_metric = report["metrics"]["field_exact_match"]
        self.assertEqual(field_metric["overall"]["correct"], 1)
        self.assertEqual(field_metric["overall"]["total"], 2)
        self.assertEqual(field_metric["overall"]["accuracy"], 0.5)
        self.assertEqual(field_metric["per_field"]["name"]["accuracy"], 1.0)
        self.assertEqual(
            field_metric["per_field"]["cnic_number"]["accuracy"], 0.0
        )

        self.assertEqual(report["metrics"]["urdu_cer"]["edit_distance"], 1)
        self.assertEqual(report["metrics"]["urdu_cer"]["reference_characters"], 3)
        self.assertAlmostEqual(report["metrics"]["urdu_cer"]["cer"], 1 / 3, places=6)

        detection = report["metrics"]["card_detection"]
        self.assertEqual(detection["true_positives"], 1)
        self.assertEqual(detection["false_positives"], 1)
        self.assertEqual(detection["false_negatives"], 1)
        self.assertEqual(detection["precision"], 0.5)
        self.assertEqual(detection["recall"], 0.5)
        self.assertEqual(detection["mean_iou"], 1.0)

        self.assertAlmostEqual(report["metrics"]["latency"]["p50_ms"], 100.0)
        memory = report["metrics"]["memory"]
        self.assertEqual(memory["baseline_rss_bytes"], 100)
        self.assertEqual(memory["warm_rss_bytes"], 120)
        self.assertEqual(memory["peak_rss_bytes"], 140)
        self.assertEqual(memory["observed_rss_delta_bytes"], 40)
        self.assertEqual(report["models"]["ocr"]["sha256"], "0" * 64)

        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(str(front), serialized)
        self.assertNotIn(str(back), serialized)
        self.assertNotIn("opaque-person-0001", serialized)
        self.assertNotIn("opaque-document-0001", serialized)
        self.assertNotIn("SYNTHETIC EXAMPLE", serialized)
        self.assertNotIn("99999-9999999-9", serialized)
        self.assertNotIn("ابج", serialized)

    def test_model_unavailability_never_produces_partial_metrics(self) -> None:
        front, back = self.create_assets()
        pair = grouped_pair(
            person="opaque-person-0001",
            document="opaque-document-0001",
            split="held_out",
            front_path=str(front),
            back_path=str(back),
        )

        def unavailable(*_args: object) -> dict:
            raise KYCError(
                "model_unavailable",
                "not exposed",
                503,
                {"component": "OCR", "reason": "weights_missing"},
            )

        report = run_benchmark(
            self.write_manifest([pair]), processor=unavailable, rss_reader=None
        )

        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["blockers"][0]["code"], "model_unavailable")
        self.assertEqual(
            report["blockers"][0]["details"]["reason"], "weights_missing"
        )
        self.assertEqual(
            report["metrics"]["field_exact_match"]["status"], "unavailable"
        )
        self.assertNotIn("accuracy", report["metrics"]["field_exact_match"])

    def test_optional_baseline_lists_regressions(self) -> None:
        current = {
            "status": "complete",
            "dataset": {
                "manifest_sha256": "a" * 64,
                "evaluated_split": "held_out",
            },
            "metrics": {
                "field_exact_match": {"overall": {"accuracy": 0.8}},
                "urdu_cer": {"cer": 0.2},
                "card_detection": {
                    "precision": 0.9,
                    "recall": 0.9,
                    "mean_iou": 0.8,
                },
                "latency": {"p50_ms": 100.0, "p95_ms": 120.0},
                "memory": {
                    "observed_rss_delta_bytes": 50,
                    "peak_rss_bytes": 1000,
                },
            },
        }
        baseline = copy.deepcopy(current)
        baseline["metrics"]["field_exact_match"]["overall"]["accuracy"] = 0.9
        baseline["metrics"]["urdu_cer"]["cer"] = 0.1
        baseline["metrics"]["latency"]["p95_ms"] = 100.0
        baseline_path = self.root / "prior.json"
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

        comparison = compare_with_baseline(current, baseline_path)

        self.assertEqual(comparison["status"], "complete")
        self.assertTrue(comparison["has_regressions"])
        regression_names = {
            item["metric"] for item in comparison["regressions"]
        }
        self.assertIn("field_exact_match.overall.accuracy", regression_names)
        self.assertIn("urdu_cer.cer", regression_names)
        self.assertIn("latency.p95_ms", regression_names)

    def test_example_manifest_is_valid_but_assets_are_deliberately_absent(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        example = repository_root / "benchmarks" / "manifest.example.json"

        manifest = load_manifest(example)
        report = run_benchmark(example)

        self.assertIn("held_out", {pair.split for pair in manifest.pairs})
        self.assertEqual(report["status"], "not_run")
        self.assertEqual(
            {blocker["code"] for blocker in report["blockers"]},
            {"front_assets_missing", "back_assets_missing"},
        )

    def test_management_command_emits_json_blocker_for_absent_manifest(self) -> None:
        output = StringIO()

        call_command(
            "benchmark_kyc",
            manifest=str(self.root / "absent.json"),
            stdout=output,
        )

        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "not_run")
        self.assertEqual(report["blockers"][0]["code"], "manifest_not_found")
