# Phase 1 completion report

Report date: 2026-09-19  
Implementation status: **complete with external measurement blockers**

Phase 1 now provides a reproducible Django service, a compatibility adapter,
safe document ingestion and request-scoped storage, contour-based card
rectification and quality gates, an EasyOCR English/Urdu baseline interface,
structured extraction/validation, and a privacy-preserving evaluation harness.
No issuance, authenticity, ownership, or biometric-verification claim is made.

## Acceptance evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Clean dependency resolution | pass | A new CPython 3.11.9 virtual environment installed the pinned graph; `pip check` reported no broken requirements. |
| Django configuration | pass | `python main.py check` reported no issues on Django 5.2.17 / DRF 3.16.1. |
| Production security settings | pass when configured | `check --deploy` reported no issues with the documented SSL, secure-cookie, HSTS, secret, and API-key variables set. |
| Fresh startup | pass | `runserver --noreload` started and `GET /health/live` returned HTTP 200 with the requested correlation ID. |
| Automated behavior | pass | 97 tests passed in the clean environment; all image fixtures are generated in memory. |
| Legacy contract | pass | Exact no-slash route, multipart names, six nominal keys, and mismatch HTTP 406 body are covered. Authentication/safety gates are intentional security changes. |
| Upload failures | pass | Tests cover empty, corrupt, unsupported, animated, oversized, over-dimension, over-pixel, EXIF-rotated, transparent, blurry, dark, glare, low-resolution, missing-card, multi-card, incomplete-card, and wrong-side behavior. |
| Concurrency isolation | pass | Threaded tests verify unique request directories/bytes, exclusive writes, and one detector construction per worker registry. |
| Evaluation leakage guard | pass | Manifest validation rejects person/document groups crossing splits before inference. Reports contain aggregate data only. |
| Measured OCR/detection accuracy | `not_run` | Required private held-out truth and provisioned model assets are absent. |

The machine-readable dry baseline is
[`benchmarks/phase1-example-result.json`](../benchmarks/phase1-example-result.json).
It records `status: not_run`, exact `front_assets_missing` and
`back_assets_missing` blockers, package/device metadata, null metrics, and no
invented scores.

## Delivered behavior

- `Requirements.txt` is a pinned reviewed runtime set; `requirements.lock` is
  the exact dependency graph from the acceptance environment.
- All secrets, upload/quality limits, retention, paths, inference device,
  languages, OCR rotation, TLS controls, and model settings are environment
  driven. Example credentials are rejected at runtime.
- Models are lazy singletons per worker. Inference on shared mutable model
  objects is serialized, CPU is the default, and CUDA is explicit/optional.
- Originals remain byte-for-byte unchanged. Processing copies use separate
  private random directories and cannot overwrite another request.
- Static JPEG/PNG/WebP content is verified by Pillow and OpenCV. EXIF is
  applied, transparent pixels are composited onto white, and animated inputs
  are rejected.
- Card contours are detected and perspective-corrected; capture failures and
  blur/exposure/glare/resolution findings return specific recapture reasons.
- Raw OCR, normalized values, evidence boxes, and uncalibrated score labels are
  retained. Missing fields remain null. Urdu Unicode/digits/order and explicit
  lifetime/no-expiry markers are handled.
- Local validation covers required fields, CNIC 5-7-1 syntax, date formats and
  ordering, expiry, detected sides, and cross-side CNIC evidence. It implements
  no fictional checksum and never equates syntax with issuance.
- Processing success and verification decisions are separate. Check statuses
  are limited to `pass`, `fail`, `uncertain`, `not_run`, and `unavailable`.
- Processing routes require API keys and throttling. CNIC-shaped request IDs are
  discarded, responses are `no-store`, storage is private, logs exclude OCR and
  identity values, and retention cleanup is explicit and guarded.

## Exact remaining blockers

1. **EasyOCR weights are absent.** `model_manifest` reports no files for
   `en,ur`. Provision `craft_mlt_25k.pth` and `arabic.pth` as documented, record
   local SHA-256 values, and restart workers.
2. **The original custom CNIC ONNX model is absent.** There is no acquisition
   source, license, checksum, class map, tensor contract, or training
   provenance. The named OpenCV contour baseline is used instead.
3. **No authorized grouped held-out corpus exists.** Field truth, Urdu logical-
   order transcripts, card geometry, and opaque person/document split IDs are
   missing. Therefore field exact match, Urdu CER, detection precision/recall/
   IoU, representative latency, peak memory, and regression comparison remain
   `not_run`/`unavailable`—not zero.
4. **Real-looking identity files remain user-owned in the workspace.** They
   were not read for evaluation, modified, or deleted. Ignore rules now cover
   the discovered locations, but the data owner must remove them and purge any
   repository history before publication.
5. **Production serving is operator work.** The acceptance run used Django's
   development server only to prove startup. A production ASGI/WSGI server,
   TLS/reverse-proxy body cap, scheduler-backed cleanup, secrets manager,
   monitoring, and access-controlled model/data volumes must be configured in
   deployment.

## Baseline and regression procedure

Provision the missing authorized assets, copy and complete the external
manifest, then run:

```powershell
python main.py benchmark_kyc --manifest D:\private-evaluation\manifest.json --split held_out --output D:\private-evaluation\phase1.json
```

The harness measures canonical per-field and aggregate exact match, logical-
order Urdu CER, detection precision/recall/mean IoU, warm p50/p95 latency, and
observed process RSS. A later run may use `--baseline` only when the manifest
hash and split match; detected regressions are reported explicitly.
