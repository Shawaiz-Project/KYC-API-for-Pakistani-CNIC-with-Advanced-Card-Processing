# Pakistani CNIC KYC API

A Django REST API for privacy-conscious Pakistani CNIC image processing. Phase
1 provides reproducible configuration, safe upload handling, card rectification
and quality gates, an EasyOCR English/Urdu baseline, structured field evidence,
local syntax/date validation, health checks, and a compatibility adapter for the
original endpoint.

This service does **not** verify issuance, identity, ownership, or authenticity
against NADRA. A well-formed CNIC number is only syntactically well formed. No
CNIC checksum is implemented or claimed, and raw model scores are not calibrated
probabilities.

## Supported Phase 1 surface

- JPEG, PNG, and WebP front/back uploads
- actual-content, byte-size, dimension, pixel-count, and decoder validation
- EXIF orientation correction, card-boundary detection, perspective correction,
  and landscape normalization
- missing/multiple/incomplete-card and wrong-side errors
- blur, exposure, glare, and minimum-resolution recapture findings
- EasyOCR 1.7.2 baseline with `en,ur`, logical Unicode/digit normalization,
  right-to-left line ordering, raw text, boxes, and uncalibrated raw scores
- `generic`, `smart`, `smart_card`, `nicop`, and `legacy_urdu` extraction schemas
- CNIC 5-7-1 syntax, required-field, date-order, expiry, lifetime/no-expiry, and
  cross-side consistency checks
- API-key authentication, throttling, request IDs, structured errors, private
  request-scoped storage, and retention cleanup
- public liveness/readiness endpoints and a grouped evaluation harness

The missing original ONNX detector is **not** reconstructed. With no configured
custom detector, the API explicitly reports and uses `opencv-contour-baseline`.

## Requirements

- CPython 3.11 (3.11.9 is the tested target)
- pip and virtual-environment support
- enough disk/RAM for PyTorch and EasyOCR model weights
- Windows: Microsoft Visual C++ 2019-or-newer runtime for ONNX Runtime
- Linux: an `en_US.UTF-8` locale and standard manylinux/OpenMP runtime libraries

The server uses `opencv-python-headless`; do not install a second GUI/contrib
OpenCV wheel in the same environment. CPU inference is the default. GPU setup is
optional and depends on a compatible NVIDIA driver/CUDA/cuDNN/PyTorch/ONNX
Runtime combination; see [model setup](docs/models.md).

## Fresh installation (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r Requirements.txt
Copy-Item .env.example .env
```

Edit `.env` before processing identity documents. At minimum, replace both
placeholder values:

```dotenv
KYC_SECRET_KEY=<long random Django secret>
KYC_API_KEYS=<one or more comma-separated random API keys>
```

Generate independent values, for example:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64)); print(secrets.token_urlsafe(32))"
```

Then initialize and acquire the pinned OCR baseline explicitly:

```powershell
python main.py migrate
python main.py check
python main.py warm_ocr_models --allow-download
python main.py model_manifest
python main.py runserver 127.0.0.1:8000
```

Runtime model downloads are disabled by default. Provisioned/offline systems
should copy pre-verified weights to `KYC_OCR_MODEL_DIR` and run the warm-up
without `--allow-download`.

Linux/macOS use the equivalent activation and copy commands:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r Requirements.txt
cp .env.example .env
```

## Health checks

```text
GET /health/live
GET /health/ready
```

Liveness returns 200 when Django can serve requests. Readiness loads/caches the
configured models once in that worker and returns 503 with explicit component
reasons until secrets, private storage, and required models are usable.

## Process a CNIC pair

```bash
curl -X POST http://127.0.0.1:8000/api/v1/kyc/process \
  -H "X-API-Key: $KYC_API_KEY" \
  -H "X-Request-ID: onboarding-42" \
  -F "front=@/private/input/front.jpg" \
  -F "back=@/private/input/back.jpg" \
  -F "template=auto"
```

`template` may be `auto`, `generic`, `smart`, `smart_card`, `nicop`, or
`legacy_urdu`. Unreadable fields are `null`; the service never fills missing
characters. See [API contract and examples](docs/api.md).

The historical no-trailing-slash endpoint remains available and keeps its old
multipart/key spelling:

```text
POST /api/v1/card/detector
front_imagee=<file>
back_image=<file>
```

It now requires the same API key and safety gates. Nominal success retains the
six legacy response keys, while all formerly accidental failures are structured.

## Tests

All automated image fixtures are generated in memory; real identity documents
are never used.

```powershell
python main.py test -v 2
```

The suite covers content validation, corruption/format/size limits, EXIF and
card rotation, missing/multiple/incomplete cards, quality gates, Unicode/Urdu
ordering, parsing/validation, model lifecycle, auth/errors, legacy compatibility,
private-storage concurrency, retention, response serialization, and split/metric
logic.

## Benchmarking

Copy `benchmarks/manifest.example.json` outside the repository, point its paths
at an authorized held-out dataset, and keep every `person_group_id` and
`document_group_id` in exactly one split:

```powershell
python main.py benchmark_kyc --manifest D:\private-evaluation\manifest.json --split held_out --output D:\private-evaluation\phase1.json
```

Use `--baseline <prior.json>` for regression comparison. The supplied workspace
has no suitable labels, split manifest, detector weight, or authorized held-out
corpus, so no accuracy, Urdu CER, detector performance, latency, or memory number
is claimed. See [baseline status](docs/baseline-results.md).

## Data protection and operations

- Identity endpoints fail closed when API keys are absent.
- Client filenames are never used for storage paths.
- Originals and PNG processing copies live in separate, random, private request
  directories with no public media URL.
- Run `python main.py cleanup_kyc_uploads` on a schedule; use `--dry-run` first.
- Application logs contain lifecycle/error type metadata only—not images, CNIC
  values, OCR text, QR payloads, biometric data, or client filenames.
- `.env`, private data directories, model weights, and evaluation data are
  ignored by Git. If sensitive files were committed previously, `.gitignore`
  cannot remove history; the data owner must purge and rotate affected data.

Audit details and remaining external blockers are in
[docs/current-state.md](docs/current-state.md). The implementation status is in
[docs/phase-1-completion.md](docs/phase-1-completion.md).

## License

Repository code is covered by [LICENSE.txt](LICENSE.txt). External datasets,
custom detector weights, EasyOCR, and its pretrained assets have their own
provenance/license obligations; record and review them before redistribution.
