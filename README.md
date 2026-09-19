# 🇵🇰 Pakistani CNIC KYC API

> **Privacy-conscious CNIC document-processing and KYC workflow platform for Pakistan**

A production-oriented **Django REST API + React/TypeScript application** for processing Pakistani CNIC documents through controlled image preprocessing, OCR, structured field extraction, validation, document-quality analysis, and configurable KYC review workflows.

The platform is designed around a **privacy-first, fail-closed architecture**. Identity documents are processed through request-scoped private storage, sensitive values are excluded from application logs, and retention cleanup is explicit and operator-controlled.

> ⚠️ **Important:** This system does **not** verify CNIC issuance, identity ownership, citizenship, or document authenticity against NADRA or any other authoritative government database.

A syntactically valid CNIC number is **not evidence of a valid or issued identity**.

---

## ✨ Overview

The project provides an extensible foundation for Pakistani identity-document workflows, progressing from deterministic image/OCR processing toward a complete KYC orchestration layer.

### Current capabilities

* 🖼️ CNIC front/back image processing
* 🔍 Card-boundary detection and perspective correction
* 🔄 EXIF orientation correction and rotation handling
* 🧠 OCR using EasyOCR with English and Urdu support
* 🔤 Unicode and digit normalization
* 📝 Structured CNIC field extraction
* ✅ Cross-field and cross-side validation
* 📐 Image-quality assessment
* 🛡️ API-key authentication and request throttling
* 🔐 Request-scoped private storage
* 🧹 Explicit retention and cleanup workflows
* 📊 Structured errors and request IDs
* ❤️ Liveness/readiness health endpoints
* 📚 OpenAPI schema and interactive API documentation
* 🧪 Synthetic/in-memory automated testing
* ⚙️ Background-processing architecture
* 👨‍💼 Reviewer/admin workflows
* 🏢 Tenant-scoped persistence
* 🔔 Signed webhook architecture
* 📦 Containerized deployment support

---

# 🏗️ Architecture

The platform is organized into three implementation phases.

```text
                         ┌─────────────────────────┐
                         │   React / TypeScript UI  │
                         │ Applicant + Admin Portal │
                         └────────────┬────────────┘
                                      │
                                      ▼
                         ┌─────────────────────────┐
                         │     Django REST API     │
                         │ Auth • Validation • KYC │
                         └────────────┬────────────┘
                                      │
             ┌────────────────────────┼────────────────────────┐
             │                        │                        │
             ▼                        ▼                        ▼
      ┌──────────────┐       ┌────────────────┐       ┌────────────────┐
      │ Image Engine │       │ OCR / Parsing  │       │ Policy Engine  │
      │ OpenCV       │       │ EasyOCR        │       │ Rules / Signals│
      └──────┬───────┘       └───────┬────────┘       └───────┬────────┘
             │                       │                        │
             └───────────────────────┼────────────────────────┘
                                     ▼
                         ┌─────────────────────────┐
                         │ KYC Processing Pipeline │
                         └────────────┬────────────┘
                                      │
              ┌───────────────────────┼────────────────────────┐
              ▼                       ▼                        ▼
       ┌──────────────┐       ┌───────────────┐        ┌──────────────┐
       │ PostgreSQL   │       │ Redis / Tasks │        │ Private      │
       │ Persistence  │       │ Background    │        │ Object Store │
       └──────────────┘       └───────────────┘        └──────────────┘
```

---

# 🚀 Implementation Phases

## Phase 1 — Reproducible Document Processing

Phase 1 establishes the deterministic document-processing foundation.

### Image validation

Supported formats:

* JPEG
* PNG
* WebP

The processing pipeline performs:

* actual-content validation
* byte-size limits
* dimension validation
* pixel-count limits
* decoder validation
* multi-frame rejection
* transparent-pixel compositing onto white
* EXIF orientation correction

### Card processing

The pipeline supports:

* card-boundary detection
* perspective correction
* landscape normalization
* missing-card detection
* multiple-card detection
* incomplete-card detection
* wrong-side detection
* 180° text fallback

### Image-quality analysis

The system can report findings related to:

* blur
* exposure
* glare
* insufficient resolution
* unsuitable image quality
* recapture recommendations

These findings are **review signals**, not independent proof of identity or document authenticity.

---

# 🧠 OCR Pipeline

Phase 1 uses:

**EasyOCR 1.7.2**

Configured languages:

```text
en
ur
```

The OCR layer supports:

* raw OCR text
* bounding boxes
* raw model scores
* Unicode normalization
* digit normalization
* right-to-left line ordering
* Urdu-aware processing
* 180° text fallback

### Important scoring limitation

OCR confidence values are **raw model scores**.

They are **not calibrated probabilities** and must not be interpreted as:

> "There is an X% probability that this field is correct."

---

# 🪪 Supported CNIC Schemas

The extraction layer currently supports:

```text
generic
smart
smart_card
nicop
legacy_urdu
```

The parser is designed to remain extensible as additional Pakistani identity-document layouts are introduced.

---

# 🔎 CNIC Validation

The system performs deterministic validation such as:

### CNIC format

```text
5-7-1
```

### Field validation

* required-field checks
* date parsing
* date ordering
* expiry validation
* lifetime/no-expiry handling
* cross-side consistency
* structured field validation

### Important limitation

No CNIC checksum algorithm is implemented or claimed.

A CNIC that matches the expected syntactic pattern should therefore be treated only as:

> **syntactically well formed**

and **not as evidence that the number exists, was issued, belongs to a person, or is currently valid.**

---

# 🛡️ KYC / Identity Verification Boundary

This distinction is fundamental to the project.

| Capability                            |  Supported |
| ------------------------------------- | ---------: |
| Image validation                      |          ✅ |
| OCR                                   |          ✅ |
| Field extraction                      |          ✅ |
| CNIC syntax validation                |          ✅ |
| Cross-side consistency                |          ✅ |
| Image-quality analysis                |          ✅ |
| Liveness workflow                     | 🔄 Phase 2 |
| Document/selfie consistency           | 🔄 Phase 2 |
| Duplicate/tamper signals              | 🔄 Phase 2 |
| Policy engine                         | 🔄 Phase 2 |
| Reviewer workflow                     | 🔄 Phase 3 |
| NADRA verification                    |          ❌ |
| CNIC ownership verification           |          ❌ |
| Government issuance verification      |          ❌ |
| Definitive authenticity determination |          ❌ |

The platform intentionally avoids representing model output as definitive identity verification.

---

# 🔐 Privacy & Security

Identity documents are highly sensitive.

The system therefore follows a **data-minimization and fail-closed design**.

### Authentication

Identity-processing endpoints require API authentication.

Requests without valid credentials are rejected.

### Request IDs

Every processing request can carry a request identifier:

```http
X-Request-ID: onboarding-42
```

This allows operational tracing without exposing identity-document contents.

### Private storage

Uploaded documents:

* are not stored using client-provided filenames
* use randomized request-scoped paths
* remain outside public media URLs
* separate original and processed images
* can be automatically removed through explicit retention cleanup

### Logging policy

Application logs intentionally exclude:

* CNIC numbers
* OCR text
* document images
* QR payloads
* biometric information
* client filenames

Logs contain lifecycle and error metadata instead.

### Cache protection

Processing and readiness responses use:

```http
Cache-Control: no-store
```

This prevents sensitive processing responses from being unintentionally cached.

---

# 🧹 Data Retention

Cleanup is explicit and operator controlled.

Run:

```powershell
python main.py cleanup_kyc_uploads --dry-run
```

After reviewing the result:

```powershell
python main.py cleanup_kyc_uploads
```

For production deployments, configure the cleanup command through an external scheduler.

The web application does **not** perform surprise recursive cleanup during normal requests.

---

# 🔑 Configuration

Create your environment file:

```powershell
Copy-Item .env.example .env
```

At minimum configure:

```dotenv
KYC_SECRET_KEY=<long-random-django-secret>
KYC_API_KEYS=<random-api-key>
```

Generate secure values:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64)); print(secrets.token_urlsafe(32))"
```

Do not commit `.env`.

Do not place production secrets inside:

* source code
* README files
* frontend bundles
* Git history
* Docker images
* public documentation

---

# 💻 Requirements

## Backend

* CPython 3.11
* pip
* virtualenv
* Django
* Django REST Framework
* OpenCV
* EasyOCR
* PyTorch
* ONNX Runtime

## Frontend

* Node.js 22
* npm 10
* React
* TypeScript

## Production infrastructure

* PostgreSQL 16
* Redis 7
* private object storage
* reverse proxy / TLS termination
* background task worker

SQLite and eager task execution remain available for reproducible local development.

---

# 🪟 Windows Installation

Create the environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Upgrade pip:

```powershell
python -m pip install --upgrade pip
```

Install pinned dependencies:

```powershell
python -m pip install -r requirements.lock
```

Create configuration:

```powershell
Copy-Item .env.example .env
```

Run migrations:

```powershell
python main.py migrate
```

Run Django checks:

```powershell
python main.py check
```

---

# 🧠 OCR Model Setup

Acquire the pinned OCR baseline explicitly:

```powershell
python main.py warm_ocr_models --allow-download
```

Inspect the model manifest:

```powershell
python main.py model_manifest
```

Then start the server:

```powershell
python main.py runserver 127.0.0.1:8000
```

### Offline deployments

Runtime downloads are disabled by default.

For offline/provisioned environments:

1. Download and verify the required model assets through an approved process.
2. Place them in `KYC_OCR_MODEL_DIR`.
3. Run the warm-up command without `--allow-download`.

```powershell
python main.py warm_ocr_models
```

---

# ⚛️ Frontend Setup

Open a second terminal:

```powershell
Set-Location frontend
npm ci
```

Create frontend configuration:

```powershell
Copy-Item .env.example .env
```

Start development:

```powershell
npm run dev
```

---

# 👤 Administrator Bootstrap

Create the initial administrator interactively:

```powershell
python main.py bootstrap_shanakht \
  --username Shawaiz \
  --email shawaiz.datascience@gmail.com
```

The administrator password is entered interactively and is **not accepted through the command line**.

Passwords must never be committed to repository files.

---

# ❤️ Health Checks

### Liveness

```http
GET /health/live
```

Returns `200` when the application process can serve requests.

### Readiness

```http
GET /health/ready
```

Readiness verifies required runtime dependencies and reports component-specific failures.

Possible readiness dependencies include:

* application configuration
* secrets
* private storage
* required models
* database
* other configured services

A failure returns:

```http
503 Service Unavailable
```

with explicit component information.

---

# 📡 API

## Process CNIC pair

```bash
curl -X POST http://127.0.0.1:8000/api/v1/kyc/process \
  -H "X-API-Key: $KYC_API_KEY" \
  -H "X-Request-ID: onboarding-42" \
  -F "front=@/private/input/front.jpg" \
  -F "back=@/private/input/back.jpg" \
  -F "template=auto"
```

Supported templates:

```text
auto
generic
smart
smart_card
nicop
legacy_urdu
```

Unreadable fields are returned as:

```json
null
```

The service does **not** invent or infer missing characters.

---

# 🔄 Legacy API Compatibility

The historical endpoint remains available:

```http
POST /api/v1/card/detector
```

Legacy multipart fields:

```text
front_imagee=<file>
back_image=<file>
```

The endpoint now uses the same API-key and safety controls.

Nominal successful responses retain the six historical response keys for compatibility, while previously accidental failures are represented through structured errors.

---

# 📚 API Documentation

OpenAPI schema:

```text
/api/schema/
```

Interactive API documentation:

```text
/api/docs/
```

Detailed contracts:

```text
docs/api.md
docs/api-v2.md
```

---

# 🧪 Testing

The test suite deliberately avoids real identity documents.

Image fixtures are generated in memory.

Run backend tests:

```powershell
python main.py test -v 2
```

Run frontend tests:

```powershell
Set-Location frontend
npm test
```

Build frontend:

```powershell
npm run build
```

### Test coverage includes

* file-content validation
* corruption handling
* format restrictions
* size limits
* dimension limits
* EXIF orientation
* card rotation
* missing cards
* multiple cards
* incomplete cards
* quality gates
* Urdu/Unicode ordering
* OCR parsing
* validation logic
* model lifecycle
* API authentication
* structured errors
* legacy compatibility
* private-storage concurrency
* retention cleanup
* response serialization
* split/metric logic

---

# 📊 Benchmarking

Benchmarking requires an authorized held-out dataset.

Create a manifest outside the repository:

```text
D:\private-evaluation\manifest.json
```

Then run:

```powershell
python main.py benchmark_kyc `
  --manifest D:\private-evaluation\manifest.json `
  --split held_out `
  --output D:\private-evaluation\phase1.json
```

For regression comparison:

```powershell
python main.py benchmark_kyc `
  --manifest D:\private-evaluation\manifest.json `
  --split held_out `
  --baseline D:\private-evaluation\previous.json `
  --output D:\private-evaluation\current.json
```

### Benchmark integrity

Keep every:

```text
person_group_id
document_group_id
```

in exactly one dataset split.

This prevents the same person's documents from leaking across training/evaluation partitions.

---

# 📈 Benchmark Status

No performance claims are currently made without an appropriate authorized evaluation corpus.

The repository does not currently claim:

* OCR accuracy
* Urdu CER/WER
* detector precision/recall
* liveness accuracy
* spoof-detection accuracy
* document-authenticity accuracy
* latency benchmarks
* memory benchmarks

The supplied workspace does not contain an appropriate authorized labeled dataset, detector weights, or evaluation split manifest.

See:

```text
docs/baseline-results.md
```

---

# 🔬 Detector Policy

The original ONNX detector weights are **not reconstructed or fabricated**.

When a custom detector is not configured, the service explicitly reports:

```text
opencv-contour-baseline
```

This distinction is intentional.

The fallback detector should not be represented as equivalent to a trained production detector.

---

# 🧩 Phase 2 — Intelligent KYC Signals

Phase 2 introduces explicit contracts for:

* document/selfie consistency
* liveness sessions
* duplicate detection signals
* tamper-review signals
* detector interfaces
* policy evaluation
* structured KYC decisions

These outputs are designed as **signals for policy/review**, rather than unsupported claims of absolute authenticity.

---

# 🏢 Phase 3 — Production KYC Platform

Phase 3 expands the service into a multi-tenant operational platform.

Planned/implemented capabilities include:

* tenant-scoped persistence
* applicant workflows
* administrator interfaces
* reviewer queues
* background processing
* private object storage
* signed webhooks
* monitoring
* operational audit metadata
* PostgreSQL persistence
* Redis-backed processing
* containerized deployment
* OpenAPI contracts

---

# 🗂️ Project Structure

A representative structure:

```text
.
├── backend/
├── frontend/
├── docs/
│   ├── api.md
│   ├── api-v2.md
│   ├── deployment.md
│   ├── models.md
│   ├── baseline-results.md
│   ├── current-state.md
│   ├── phase-1-completion.md
│   ├── phase-2-completion.md
│   └── phase-3-completion.md
├── benchmarks/
├── requirements.lock
├── Requirements.txt
├── .env.example
├── .gitignore
├── main.py
└── LICENSE.txt
```

---

# ☁️ Production Deployment

Production deployments should include:

```text
                    Internet
                       │
                       ▼
                 ┌───────────┐
                 │ TLS Proxy │
                 └─────┬─────┘
                       │
                       ▼
              ┌─────────────────┐
              │ Django API      │
              └───────┬─────────┘
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
     PostgreSQL     Redis     Object Storage
          │           │           │
          │           ▼           │
          │      Task Workers     │
          │                       │
          └──────────┬────────────┘
                     ▼
               KYC Pipeline
```

Production environments should use:

* HTTPS/TLS
* secure cookies
* HSTS where appropriate
* controlled reverse-proxy configuration
* strict request-body limits
* private object storage
* database backups
* secret management
* scheduled retention cleanup
* monitoring and alerting
* restricted administrative access

---

# 🔒 Reverse Proxy Security

Configure the application request limit:

```dotenv
KYC_MAX_REQUEST_BYTES=<limit>
```

The reverse proxy should enforce a request-body limit **no larger than** the application limit.

Only enable:

```dotenv
KYC_TRUST_PROXY_SSL_HEADER=true
```

when the deployment architecture prevents untrusted clients from spoofing forwarded protocol headers.

---

# 🌐 CORS / CSRF

Browser clients served from another origin must be explicitly configured.

Use:

```dotenv
KYC_CSRF_TRUSTED_ORIGINS=<trusted-origins>
```

Do not use unrestricted production values such as:

```text
*
```

for sensitive identity-processing applications unless the surrounding security architecture explicitly requires it and has been reviewed.

The local development configuration permits the Vite development origin on port `5173`.

---

# 🚨 Sensitive Data Handling

Never commit:

```text
.env
identity documents
OCR output
CNIC numbers
selfies
biometric information
evaluation datasets
model weights with restricted provenance
database files
production secrets
API keys
private webhook secrets
```

The repository ignores private runtime directories, model assets, environment files, and evaluation data.

### Git history warning

Adding a sensitive file to `.gitignore` does **not** remove previously committed copies.

If sensitive material has entered Git history:

1. remove the material from the repository
2. rewrite affected history where appropriate
3. rotate exposed credentials/secrets
4. invalidate compromised keys
5. assess whether affected data requires incident handling

---

# ⚠️ Security & Compliance Notice

This software is an engineering/research implementation and does not by itself establish compliance with Pakistani law, banking regulations, data-protection requirements, contractual obligations, or the requirements of a particular KYC provider.

Before processing real identity documents in production, conduct appropriate:

* security review
* threat modeling
* privacy review
* access-control review
* penetration testing
* data-retention review
* incident-response planning
* legal/compliance assessment
* third-party license review

The operator is responsible for determining whether the deployment is lawful and appropriate for its intended use.

---

# ⚖️ Limitations

This project intentionally does **not** claim:

* NADRA verification
* identity ownership verification
* government-issued authenticity verification
* definitive document authenticity
* biometric identity verification
* calibrated probability estimates
* universal CNIC layout recognition
* production-grade detector performance without validated weights
* production-grade liveness performance without validated evaluation
* accuracy metrics without an authorized held-out dataset

Model scores, detector outputs, image-quality findings, and consistency signals should be treated as **inputs to a controlled decision process**, not as unquestionable truth.

---

# 📖 Documentation

| Document                                                   | Purpose                      |
| ---------------------------------------------------------- | ---------------------------- |
| [`docs/api.md`](docs/api.md)                               | API contract and examples    |
| [`docs/api-v2.md`](docs/api-v2.md)                         | Phase 2/3 API contracts      |
| [`docs/models.md`](docs/models.md)                         | Model setup and lifecycle    |
| [`docs/deployment.md`](docs/deployment.md)                 | Deployment and operations    |
| [`docs/baseline-results.md`](docs/baseline-results.md)     | Benchmark status             |
| [`docs/current-state.md`](docs/current-state.md)           | Current implementation state |
| [`docs/phase-1-completion.md`](docs/phase-1-completion.md) | Phase 1 status               |
| [`docs/phase-2-completion.md`](docs/phase-2-completion.md) | Phase 2 status               |
| [`docs/phase-3-completion.md`](docs/phase-3-completion.md) | Phase 3 status               |

---

# 🛣️ Roadmap

### Phase 1

* [x] Image validation
* [x] Preprocessing
* [x] Card detection baseline
* [x] Perspective correction
* [x] OCR
* [x] Structured extraction
* [x] CNIC syntax validation
* [x] Cross-side validation
* [x] API authentication
* [x] Private request storage
* [x] Retention cleanup
* [x] OpenAPI
* [x] Automated tests

### Phase 2

* [x/partial] Detector contracts
* [x/partial] Document/selfie consistency signals
* [x/partial] Liveness sessions
* [x/partial] Duplicate signals
* [x/partial] Tamper-review signals
* [x/partial] Policy engine

### Phase 3

* [x/partial] Tenant isolation
* [x/partial] Reviewer workflows
* [x/partial] Background processing
* [x/partial] Private object storage
* [x/partial] Signed webhooks
* [x/partial] Monitoring
* [x/partial] Applicant/admin interfaces
* [x/partial] Containerized deployment

> The exact implementation status is maintained in the phase completion documents rather than inferred from this roadmap.

---

# 🤝 Contributing

Contributions are welcome.

Before submitting a pull request:

1. Keep sensitive identity data out of the repository.
2. Do not add real CNIC documents to tests.
3. Prefer synthetic or generated fixtures.
4. Add tests for security-sensitive changes.
5. Update API documentation when contracts change.
6. Document model/provenance changes.
7. Do not introduce undocumented external data dependencies.
8. Preserve backward compatibility where explicitly required.
9. Run the complete backend and frontend test suites.
10. Review third-party licenses before adding dependencies.

---

# 📜 License

Repository code is licensed under the **MIT License**.

See:

```text
LICENSE.txt
```

Third-party software, pretrained models, datasets, fonts, images, detector weights, OCR assets, APIs, and other external resources may be subject to separate licenses and terms.

The MIT License for this repository does **not** automatically grant rights to third-party materials.

Before redistribution or commercial deployment, review and record the applicable licenses and provenance for every external component.

---

# 👨‍💻 Author

**Shawaiz Ali**

Data Scientist & AI/ML Engineer

* GitHub: `Shawaiz-Project`
* Portfolio: `shawaiz-project.github.io`
* Kaggle: `shawaizdatascience`
* ORCID: `0009-0005-2409-2717`

---

## ⭐ Project Philosophy

> **Process carefully. Store minimally. Validate explicitly. Fail closed. Never confuse extraction with verification.**

This project is built around a simple principle:

**A document-processing system should clearly distinguish what it observed, what it inferred, what it validated, and what it cannot know.**

That distinction is especially important when working with identity documents and KYC workflows.
