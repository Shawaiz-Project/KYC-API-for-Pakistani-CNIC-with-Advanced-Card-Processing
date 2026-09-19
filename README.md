# Pakistani CNIC KYC API

A Django REST API and React/TypeScript web application for privacy-conscious
Pakistani CNIC workflows. Phase 1 provides reproducible image processing and
structured OCR. Phase 2 adds explicit detector contracts, document/selfie
consistency signals, liveness sessions, duplicate/tamper review signals, and a
policy layer. Phase 3 adds tenant-scoped persistence, reviewer workflows,
background processing, private object storage, signed webhooks, monitoring,
OpenAPI, containers, and applicant/admin interfaces.

This service does **not** verify issuance, identity, ownership, or authenticity
against NADRA. A well-formed CNIC number is only syntactically well formed. No
CNIC checksum is implemented or claimed, and raw model scores are not calibrated
probabilities.

## Supported Phase 1 surface

- static JPEG, PNG, and WebP front/back uploads; transparent pixels are
  composited onto white before processing and multi-frame images are rejected
- actual-content, byte-size, dimension, pixel-count, and decoder validation
- EXIF orientation correction, card-boundary detection, perspective correction,
  and landscape normalization
- missing/multiple/incomplete-card and wrong-side errors
- blur, exposure, glare, and minimum-resolution recapture findings
- EasyOCR 1.7.2 baseline with `en,ur`, logical Unicode/digit normalization,
  right-to-left line ordering, 180-degree text fallback, raw text, boxes, and
  uncalibrated raw scores
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
- Node.js 22 and npm 10 for frontend development
- PostgreSQL 16 and Redis 7 for the production/staging profile (SQLite and
  eager tasks remain the reproducible local-development defaults)

The server uses `opencv-python-headless`; do not install a second GUI/contrib
OpenCV wheel in the same environment. CPU inference is the default. GPU setup is
optional and depends on a compatible NVIDIA driver/CUDA/cuDNN/PyTorch/ONNX
Runtime combination; see [model setup](docs/models.md).

## Fresh installation (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
Copy-Item .env.example .env
```

Edit `.env` before processing identity documents. At minimum, replace both
placeholder values. The server deliberately rejects the example values and API
keys shorter than 24 characters:

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

In another terminal, start the frontend:

```powershell
Set-Location frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

Create the initial administrator interactively; the password is never accepted
on the command line or stored in repository files:

```powershell
python main.py bootstrap_shanakht --username Shawaiz --email shawaiz.datascience@gmail.com
```

Runtime model downloads are disabled by default. Provisioned/offline systems
should copy pre-verified weights to `KYC_OCR_MODEL_DIR` and run the warm-up
without `--allow-download`.

Linux/macOS use the equivalent activation and copy commands:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
cp .env.example .env
```

`requirements.lock` is the exact dependency graph used for the Windows
CPython 3.11 acceptance run. `Requirements.txt` contains the reviewed, pinned
direct/inference dependency set and is the source used when intentionally
refreshing the lock.

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
Set-Location frontend
npm test
npm run build
```

The generated OpenAPI schema is available at `/api/schema/` and interactive
documentation at `/api/docs/`. Phase 2/3 contracts and examples are in
[docs/api-v2.md](docs/api-v2.md). Deployment, backup/restore, model replacement,
and rollback instructions are in [docs/deployment.md](docs/deployment.md).

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
- Configure that command in the host scheduler at least as often as the desired
  retention window; the web process never performs surprise recursive cleanup.
- Application logs contain lifecycle/error type metadata only—not images, CNIC
  values, OCR text, QR payloads, biometric data, or client filenames.
- The local SQLite database lives at ignored `var/shanakht.sqlite3`; the legacy
  tracked `Django Api/db.sqlite3` is removed from the working tree so password
  hashes and future application metadata cannot be committed accidentally.
- Browser frontends served from another origin must be listed in
  `KYC_CSRF_TRUSTED_ORIGINS`. The example permits the local Vite development
  origins on port 5173.
- `.env`, private data directories, model weights, and evaluation data are
  ignored by Git. If sensitive files were committed previously, `.gitignore`
  cannot remove history; the data owner must purge and rotate affected data.

For production, terminate TLS at the service or a controlled reverse proxy,
set the `KYC_SECURE_*` cookie/redirect/HSTS options in `.env`, and enable
`KYC_TRUST_PROXY_SSL_HEADER` only when untrusted clients cannot set the forwarded
protocol header. The proxy must enforce a request-body limit no larger than
`KYC_MAX_REQUEST_BYTES`; the application also enforces Content-Length and a
streaming aggregate file-byte cap. Processing and readiness responses carry
`Cache-Control: no-store`.

Audit details and remaining external blockers are in
[docs/current-state.md](docs/current-state.md). The implementation status is in
[docs/phase-1-completion.md](docs/phase-1-completion.md),
[docs/phase-2-completion.md](docs/phase-2-completion.md), and
[docs/phase-3-completion.md](docs/phase-3-completion.md).

## License

Repository code is covered by [LICENSE.txt](LICENSE.txt). External datasets,
custom detector weights, EasyOCR, and its pretrained assets have their own
provenance/license obligations; record and review them before redistribution.
