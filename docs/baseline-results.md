# Phase 1 baseline results

Baseline record date: 2026-09-14  
Result state: **blocked / not run**

No accuracy or production performance value can be reported from the supplied
workspace. The repository contains no usable detector weight, authorized and
annotated held-out dataset, Urdu ground truth, card-boundary labels, or grouped
split manifest. The few existing images are real-looking, unlabelled identity
documents with no provenance/license and are therefore excluded.

## Metric status

| Metric | Status | Value | Exact blocker |
| --- | --- | --- | --- |
| Overall/per-field exact match | `not_run` | `null` | No held-out expected-field annotations; OCR assets absent at audit. |
| Urdu character error rate | `not_run` | `null` | No authorized Urdu transcription truth; OCR assets absent at audit. |
| Detection precision | `not_run` | `null` | No held-out card boxes/polygons; original ONNX weight absent. |
| Detection recall | `not_run` | `null` | No held-out card boxes/polygons; original ONNX weight absent. |
| Detection mean IoU | `not_run` | `null` | No held-out card boxes/polygons; original ONNX weight absent. |
| Warm latency p50/p95 | `not_run` | `null` | No representative authorized held-out inputs with loadable production models. |
| Observed process RSS/peak | `not_run` | `null` | No representative authorized held-out run with loadable production models. |
| Regression comparison | `unavailable` | `null` | No prior valid baseline result under the same manifest/model/threshold contract. |

These statuses are not zero scores. They mean the measurement prerequisites are
absent. Unit tests and a synthetic smoke request validate behavior, not model
accuracy or production performance.

## Audited machine context

- OS: Windows x64
- Python: CPython 3.11.9
- Device mode: CPU default
- Original Django startup: failed before Phase 1 (`yolov8` import missing)
- Original model inventory: no ONNX/PyTorch model weights in workspace
- Original evaluation inventory: no annotations, manifests, splits, or results

The maintained service starts and test behavior is measured separately in the
[Phase 1 completion report](phase-1-completion.md). A synthetic diagnostic is
not substituted for a held-out accuracy or latency benchmark.

## How to produce the first valid baseline

1. Provision EasyOCR weights and record their SHA-256 manifest.
2. If evaluating the trained detector, provision its documented ONNX weight,
   license/provenance, class map, and SHA-256.
3. Create an external manifest based on `benchmarks/manifest.example.json`.
4. Include opaque person/document grouping IDs and ensure neither group crosses
   train/validation/test splits.
5. Supply expected normalized fields, Urdu transcription, and card geometry for
   every evaluated side.
6. Run:

   ```powershell
   python main.py benchmark_kyc --manifest D:\private-evaluation\manifest.json --split test --output D:\private-evaluation\phase1.json
   ```

7. Review the emitted blockers. Only publish metrics when their status is
   `measured`, together with manifest version, model/package versions, full
   weight checksums, thresholds, device/hardware, and seed.
8. On later runs, add `--baseline` pointing to the first result. Treat any
   detected metric regression as an investigation item; do not hide it by
   changing split membership.
