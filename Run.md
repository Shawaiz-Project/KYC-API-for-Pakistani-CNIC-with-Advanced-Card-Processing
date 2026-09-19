# 🇵🇰 Shanakht — KYC API for Pakistani CNIC

## Complete Local Development & Testing Guide

> **Project:** Shanakht
> **Purpose:** Privacy-conscious processing, OCR, validation, and review workflows for Pakistani CNIC images
> **Backend:** Django REST Framework
> **Frontend:** React + TypeScript + Vite
> **Development Database:** SQLite
> **Production Database:** PostgreSQL
> **OCR:** EasyOCR
> **Computer Vision:** OpenCV
> **Runtime:** Python 3.11 + Node.js 22

---

# 📋 Table of Contents

1. [System Overview](#1-system-overview)
2. [Requirements](#2-requirements)
3. [Project Structure](#3-project-structure)
4. [First-Time Installation](#4-first-time-installation)
5. [Environment Configuration](#5-environment-configuration)
6. [Generate Secure Secrets](#6-generate-secure-secrets)
7. [Initialize Database](#7-initialize-database)
8. [Install and Prepare OCR Models](#8-install-and-prepare-ocr-models)
9. [Create Administrator Account](#9-create-administrator-account)
10. [Start the Backend](#10-start-the-backend)
11. [Start the Frontend](#11-start-the-frontend)
12. [Verify the Installation](#12-verify-the-installation)
13. [Applicant Workflow](#13-applicant-workflow)
14. [Administrator Workflow](#14-administrator-workflow)
15. [Direct API Testing](#15-direct-api-testing)
16. [Legacy API Testing](#16-legacy-api-testing)
17. [Phase 2/3 API](#17-phase-23-api)
18. [Automated Testing](#18-automated-testing)
19. [Health Checks](#19-health-checks)
20. [Common Problems](#20-common-problems)
21. [Security Checklist](#21-security-checklist)
22. [Data & Storage Management](#22-data--storage-management)
23. [Reset Local Development Environment](#23-reset-local-development-environment)
24. [Stopping the Application](#24-stopping-the-application)
25. [Useful URLs](#25-useful-urls)
26. [Development vs Production](#26-development-vs-production)
27. [Final Verification Checklist](#27-final-verification-checklist)

---

# 1. System Overview

Shanakht is a Django REST + React application for processing Pakistani identity-document images through a controlled KYC workflow.

The local development architecture is:

```text
┌──────────────────────────────────────────────────────┐
│                  React / TypeScript                  │
│                    Vite Frontend                    │
│                  localhost:5173                     │
└───────────────────────┬──────────────────────────────┘
                        │
                        │ HTTP / Session / API
                        ▼
┌──────────────────────────────────────────────────────┐
│                    Django API                       │
│                  127.0.0.1:8000                    │
├──────────────────────────────────────────────────────┤
│ Authentication │ KYC │ OCR │ Validation │ Review   │
└─────────┬──────────────┬──────────────┬─────────────┘
          │              │              │
          ▼              ▼              ▼
     ┌─────────┐   ┌───────────┐   ┌──────────────┐
     │ SQLite  │   │ EasyOCR   │   │ Private      │
     │   Dev   │   │ + OpenCV  │   │ Runtime Data │
     └─────────┘   └───────────┘   └──────────────┘
```

### Important verification boundary

This application performs document processing and KYC-related checks.

It does **not**, by itself:

* verify CNIC issuance with NADRA
* establish identity ownership
* prove that an applicant is the person named on the document
* provide definitive document authenticity verification
* implement or claim a CNIC checksum
* turn OCR scores into calibrated probabilities

---

# 2. Requirements

## 2.1 Required Software

| Component | Required Version       |
| --------- | ---------------------- |
| Python    | CPython 3.11.x         |
| Node.js   | 22.x                   |
| npm       | 10.x                   |
| OS        | Windows 10/11 or Linux |
| RAM       | 4 GB minimum           |
| Git       | Recommended            |

EasyOCR and PyTorch model assets can require substantially more memory depending on the environment.

---

## 2.2 Windows Requirement

Windows systems using ONNX Runtime should have the Microsoft Visual C++ 2019-or-newer Redistributable installed.

Official installer:

https://aka.ms/vs/17/release/vc_redist.x64.exe

---

## 2.3 Recommended Hardware

For comfortable local development:

* 8 GB+ RAM
* SSD storage
* modern multi-core CPU
* stable internet connection for initial model downloads

GPU acceleration is optional.

CPU inference remains the default development configuration.

---

# 3. Project Structure

A typical project layout is:

```text
Shanakht/
│
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── .env
│
├── Django Api/
│   ├── manage.py
│   └── ...
│
├── docs/
│
├── benchmarks/
│
├── var/
│   ├── models/
│   └── shanakht.sqlite3
│
├── .venv/
├── .env
├── .env.example
├── requirements.lock
├── Requirements.txt
├── main.py
├── LICENSE.txt
└── RUN.md
```

### Git-ignored runtime content

The following should remain outside Git:

```text
.env
.venv/
var/
model weights
uploaded identity documents
evaluation datasets
private runtime artifacts
```

---

# 4. First-Time Installation

## 4.1 Open PowerShell

Open PowerShell in the project root:

```powershell
Set-Location "C:\path\to\Shanakht"
```

Replace the path with your actual project location.

---

# 4.2 Create Python Virtual Environment

```powershell
py -3.11 -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Verify Python:

```powershell
python --version
```

Expected:

```text
Python 3.11.x
```

---

# 4.3 Upgrade pip

```powershell
python -m pip install --upgrade pip
```

---

# 4.4 Install Backend Dependencies

Use the locked dependency set:

```powershell
python -m pip install -r requirements.lock
```

Verify Django:

```powershell
python -m django --version
```

---

# 4.5 Install Frontend Dependencies

Open a second PowerShell terminal or continue in the same terminal:

```powershell
Set-Location frontend
npm ci
```

Create the frontend environment file:

```powershell
Copy-Item .env.example .env
```

Return to the project root:

```powershell
Set-Location ..
```

---

# 5. Environment Configuration

The backend configuration is stored in:

```text
.env
```

Create it from the provided template:

```powershell
Copy-Item .env.example .env
```

The server intentionally rejects placeholder security values.

At minimum, configure:

```dotenv
KYC_SECRET_KEY=<secure-random-secret>
KYC_API_KEYS=<secure-random-api-key>
```

For local development, the example configuration can be retained for non-sensitive development options.

---

# 6. Generate Secure Secrets

Generate independent values:

```powershell
python -c "import secrets; print('SECRET_KEY:', secrets.token_urlsafe(64)); print('API_KEY:', secrets.token_urlsafe(32))"
```

Example:

```text
SECRET_KEY: <generated-secret>
API_KEY:    <generated-api-key>
```

Never copy the example values from documentation into a real deployment.

Update `.env`:

```dotenv
KYC_SECRET_KEY=<generated-secret>
KYC_API_KEYS=<generated-api-key>
```

### API key usage

The API key is supplied through:

```http
X-API-Key: <your-api-key>
```

---

## 6.1 Development Debug Mode

For local development:

```dotenv
KYC_DEBUG=true
```

Do **not** treat development debug configuration as a production security configuration.

Production should use an appropriately hardened configuration.

---

# 7. Initialize Database

From the project root:

```powershell
python main.py migrate
```

This creates the local development database:

```text
var/shanakht.sqlite3
```

Run the Django configuration check:

```powershell
python main.py check
```

Expected result:

```text
System check identified no issues
```

If configuration errors are reported, resolve them before starting the server.

---

# 8. Install and Prepare OCR Models

Shanakht uses EasyOCR for the baseline OCR pipeline.

Download and initialize the required model assets:

```powershell
python main.py warm_ocr_models --allow-download
```

The first execution downloads the required model weights.

Then inspect the loaded model configuration:

```powershell
python main.py model_manifest
```

---

## 8.1 Offline / Air-Gapped Environment

If the environment cannot download models at runtime:

1. Obtain the required model files through an approved process.
2. Copy them into:

```text
var/models/easyocr/
```

3. Run:

```powershell
python main.py warm_ocr_models
```

Do not use:

```text
--allow-download
```

when downloads are intentionally disabled.

---

# 9. Create Administrator Account

Create the initial administrator:

```powershell
python main.py bootstrap_shanakht `
  --username Shawaiz `
  --email shawaiz.datascience@gmail.com
```

The command prompts for a password interactively.

The password should:

* not be passed through command-line arguments
* not be written into `.env`
* not be committed to Git
* not be stored in documentation

After creation, the administrator can access:

```text
http://localhost:5173/auth
```

and:

```text
http://127.0.0.1:8000/admin/
```

---

# 10. Start the Backend

Open **Terminal 1**.

From the project root:

```powershell
.\.venv\Scripts\python.exe "Django Api\manage.py" runserver 127.0.0.1:8000
```

Expected output:

```text
Watching for file changes with StatReloader
System check identified no issues
Starting development server at http://127.0.0.1:8000/
```

Keep this terminal running.

---

# 11. Start the Frontend

Open **Terminal 2**.

Navigate to the frontend:

```powershell
Set-Location frontend
```

Start Vite:

```powershell
npm run dev
```

Expected output resembles:

```text
VITE v7.x ready in ~2000 ms

Local: http://localhost:5173/
```

Keep this terminal running.

---

# 12. Verify the Installation

Before uploading identity documents, verify the application components.

## 12.1 Backend

Open:

```text
http://127.0.0.1:8000/
```

---

## 12.2 Swagger

Open:

```text
http://127.0.0.1:8000/api/docs/
```

---

## 12.3 OpenAPI Schema

Open:

```text
http://127.0.0.1:8000/api/schema/
```

---

## 12.4 Frontend

Open:

```text
http://localhost:5173/
```

---

## 12.5 Liveness

Run:

```powershell
curl.exe http://127.0.0.1:8000/health/live
```

A successful response should return HTTP `200`.

---

## 12.6 Readiness

Run:

```powershell
curl.exe http://127.0.0.1:8000/health/ready
```

A successful response should return HTTP `200`.

If it returns `503`, inspect the JSON response for the unavailable component.

Typical causes include:

* missing secrets
* unavailable private storage
* OCR model weights not prepared
* incomplete environment configuration

---

# 13. Applicant Workflow

The web application provides an applicant-facing KYC workflow.

```text
Sign In
   ↓
Applicant Dashboard
   ↓
Start Verification
   ↓
Upload CNIC Front
   ↓
Upload CNIC Back
   ↓
Selfie
   ↓
Liveness
   ↓
Review + Consent
   ↓
Submit
   ↓
Results
```

---

## 13.1 Applicant Sign In

Open:

```text
http://localhost:5173/auth
```

Enter the applicant credentials.

Applicants are redirected to:

```text
/app
```

Applicant accounts can be created or managed through Django Admin.

---

# 13.2 Start a New Verification

Open:

```text
/app
```

Select:

**Start new verification**

A new KYC application record is created.

---

# 13.3 Upload CNIC Front & Back

Open:

```text
/app/new/document
```

Upload:

* Front image
* Back image

Supported formats:

```text
JPG
PNG
WebP
```

### Recommended image conditions

* Use a photograph of the physical document.
* Keep all four card edges visible.
* Avoid glare and reflections.
* Use adequate lighting.
* Avoid severe blur.
* Do not crop important document regions.
* Maximum image size: 10 MB.
* Minimum recommended resolution: 640 × 400 px.
* The card should occupy a meaningful portion of the image.

The server performs the authoritative validation and quality checks.

---

# 13.4 Selfie Capture

Open:

```text
/app/new/selfie
```

The applicant can:

* use the webcam
* upload a selfie image

Recommended capture conditions:

* face the camera directly
* use even lighting
* avoid sunglasses
* avoid hats or face-obscuring objects
* ensure only one face is present

Select:

**Continue to liveness**

---

# 13.5 Liveness Challenge

Open:

```text
/app/new/liveness
```

Select:

**Start challenge**

The server issues a randomized challenge.

The applicant follows the displayed instructions.

Example actions may include:

```text
Turn left
Turn right
Look center
```

### Local-development behavior

If a production anti-spoofing/liveness model is not deployed, the workflow can route the application to manual review.

This is expected behavior and should not be interpreted as successful automated liveness verification.

---

# 13.6 Review & Submit

Open:

```text
/app/new/review
```

Review:

* CNIC front
* CNIC back
* selfie

Confirm the consent statement:

> I consent to processing my documents and selfie for this verification.

Select:

**Submit application**

The application is then processed and the user is redirected to the results page.

---

# 13.7 Results

Open:

```text
/app/results/<id>
```

The results interface can display:

| Result            | Meaning                                  |
| ----------------- | ---------------------------------------- |
| `checks_passed`   | Configured checks completed successfully |
| `needs_review`    | Human review is required                 |
| `needs_recapture` | New evidence/image capture is required   |
| `checks_failed`   | Configured checks failed                 |

Results can include:

* detector status
* reason codes
* model version
* execution time
* OCR-extracted fields
* validation results
* consistency results
* official-verification status

### Official verification

Official verification remains:

```text
unavailable
```

unless an authorized external verification integration is configured.

---

# 14. Administrator Workflow

Administrators manage applications and review uncertain cases.

---

## 14.1 Admin Sign In

Open:

```text
http://localhost:5173/auth
```

Sign in using the administrator account.

Admins are redirected to:

```text
/admin
```

---

# 14.2 Application Dashboard

Open:

```text
http://localhost:5173/admin/applications
```

The dashboard provides:

* application listing
* status information
* application details
* access to reviewer workflows

---

# 14.3 Review Queue

Open:

```text
http://localhost:5173/admin/review
```

This view is intended for applications requiring human attention.

Typical outcomes include:

```text
needs_review
checks_failed
```

---

# 14.4 Reviewer Workspace

Open:

```text
http://localhost:5173/admin/review/<id>
```

The workspace provides two major areas.

### Evidence

* protected front image
* protected back image
* selfie evidence
* detector results
* reason codes
* model versions

### Decision Panel

Reviewers can:

* inspect extracted information
* correct OCR fields
* record correction reasons
* approve configured checks
* request recapture
* fail configured checks

Available actions:

```text
Approve checks
Request recapture
Fail checks
```

These actions represent application workflow decisions and should not be interpreted as independent proof of government-issued identity.

---

# 14.5 API Key Management

Open:

```text
http://localhost:5173/admin/api
```

Administrators can:

* create integration API keys
* assign scopes
* configure quotas
* rotate keys
* revoke keys

Available scopes include:

```text
applications:read
applications:write
```

### Important

API keys are displayed only when created.

Copy and securely store a key immediately.

Never commit an API key to Git.

---

# 14.6 Django Admin

Open:

```text
http://127.0.0.1:8000/admin/
```

Django Admin can be used to manage:

* users
* organizations
* roles
* application records
* audit events
* administrative data

Supported roles include:

```text
admin
reviewer
applicant
api_client
```

---

# 15. Direct API Testing

There are two recommended ways to test the primary KYC API.

---

## 15.1 Swagger UI

Open:

```text
http://127.0.0.1:8000/api/docs/
```

Then:

1. Select **Authorize**.
2. Enter the API key from `.env`.
3. Find:

```text
POST /api/v1/kyc/process
```

4. Select **Try it out**.
5. Upload the front image.
6. Upload the back image.
7. Set:

```text
template=auto
```

8. Select **Execute**.
9. Inspect the JSON response.

---

# 15.2 curl / PowerShell

Set the API key:

```powershell
$API_KEY = "<your-api-key>"
```

Process a CNIC pair:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/kyc/process `
  -H "X-API-Key: $API_KEY" `
  -H "X-Request-ID: test-run-001" `
  -F "front=@C:\path\to\cnic_front.jpg" `
  -F "back=@C:\path\to\cnic_back.jpg" `
  -F "template=auto"
```

Do not place real production identity documents in publicly shared command histories or screenshots.

---

# 16. Legacy API Testing

The historical endpoint remains available for backward compatibility.

Endpoint:

```text
POST /api/v1/card/detector
```

PowerShell:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/card/detector `
  -H "X-API-Key: $API_KEY" `
  -F "front_imagee=@C:\path\to\cnic_front.jpg" `
  -F "back_image=@C:\path\to\cnic_back.jpg"
```

### Legacy field name

The field:

```text
front_imagee
```

contains the historical spelling and is intentionally retained for compatibility.

Do not rename it without considering existing clients.

---

# 17. Phase 2/3 API

The newer application API uses browser session authentication and CSRF protection.

The easiest way to test these endpoints is through:

```text
http://127.0.0.1:8000/api/docs/
```

or the React frontend.

Available routes include:

```text
GET  /api/v2/applications
GET  /api/v2/applications/<id>

POST /api/v2/applications
POST /api/v2/applications/<id>/artifacts
POST /api/v2/applications/<id>/consent
POST /api/v2/applications/<id>/submit

POST /api/v2/applications/<id>/decisions
POST /api/v2/applications/<id>/corrections
POST /api/v2/applications/<id>/assignment

GET  /api/v2/auth/me
POST /api/v2/auth/sign-in
POST /api/v2/auth/sign-out
```

---

# 18. Automated Testing

## 18.1 Backend

From the project root:

```powershell
python main.py test -v 2
```

The test suite uses generated/in-memory image fixtures.

Real identity documents are not required.

Coverage includes:

* content validation
* corruption handling
* file-size restrictions
* format validation
* EXIF orientation
* rotation
* missing cards
* multiple cards
* incomplete cards
* blur
* exposure
* glare
* Urdu/Unicode ordering
* OCR parsing
* field validation
* authentication
* throttling
* structured errors
* storage concurrency
* retention

---

## 18.2 Frontend

```powershell
Set-Location frontend
npm test
```

Build the production frontend:

```powershell
npm run build
```

A successful build confirms that the frontend compiles successfully.

---

# 19. Health Checks

## Liveness

```powershell
curl.exe http://127.0.0.1:8000/health/live
```

Purpose:

> Verify that Django can serve requests.

Expected:

```text
HTTP 200
```

---

## Readiness

```powershell
curl.exe http://127.0.0.1:8000/health/ready
```

Purpose:

> Verify that required runtime dependencies are ready.

Expected:

```text
HTTP 200
```

Possible failure:

```text
HTTP 503
```

The response should identify the component preventing readiness.

---

# 20. Common Problems

| Problem                   | Recommended Action                                                  |
| ------------------------- | ------------------------------------------------------------------- |
| `ModuleNotFoundError`     | Activate `.venv` and reinstall dependencies                         |
| `drf_spectacular` missing | Run `python -m pip install -r requirements.lock`                    |
| Invalid `KYC_SECRET_KEY`  | Generate a fresh secret and update `.env`                           |
| Invalid `KYC_API_KEYS`    | Generate a fresh API key                                            |
| `401 Unauthorized`        | Check `X-API-Key` against `KYC_API_KEYS`                            |
| `/health/ready` = `503`   | Inspect readiness response and prepare missing models/configuration |
| OCR model unavailable     | Run `python main.py warm_ocr_models --allow-download`               |
| Frontend CSRF error       | Add the frontend origin to `KYC_CSRF_TRUSTED_ORIGINS`               |
| Frontend cannot reach API | Confirm Django is running on port `8000`                            |
| Port `8000` occupied      | Stop the conflicting process or choose another development port     |
| Port `5173` occupied      | Stop the conflicting Vite process or use Vite's assigned port       |
| `manage.py` path error    | Run from the repository root and use the documented path            |
| Image rejected            | Check format, size, resolution, blur, glare, and card visibility    |
| Wrong-side error          | Verify the correct front/back images were uploaded                  |
| OCR fields are `null`     | Improve image quality or use the appropriate document template      |
| Liveness routes to review | Expected when an anti-spoofing model is not deployed                |

---

# 21. Security Checklist

Before processing sensitive documents, verify:

```text
[ ] .env exists locally
[ ] Production secrets are not placeholders
[ ] .env is ignored by Git
[ ] API keys are not committed
[ ] Identity documents are not committed
[ ] Model weights are not accidentally committed
[ ] Evaluation datasets are outside the repository
[ ] Debug mode is appropriate for the environment
[ ] Private storage is enabled
[ ] Retention cleanup is configured
[ ] HTTPS is used for non-local deployments
[ ] CORS/CSRF origins are restricted
[ ] Request-body limits are configured
[ ] Administrative accounts use strong passwords
[ ] API keys are scoped appropriately
[ ] API keys can be revoked/rotated
```

---

# 22. Data & Storage Management

Runtime data is intentionally separated from source code.

Typical local runtime directory:

```text
var/
├── models/
└── shanakht.sqlite3
```

Uploaded documents and processing artifacts should remain private.

Never expose sensitive runtime directories through a public web server.

---

## 22.1 Cleanup

Preview cleanup first:

```powershell
python main.py cleanup_kyc_uploads --dry-run
```

Execute cleanup:

```powershell
python main.py cleanup_kyc_uploads
```

Production deployments should schedule this operation according to the documented retention policy.

---

# 23. Reset Local Development Environment

⚠️ **This section can delete local development data.**

Before resetting, stop Django and Vite.

If you need a fresh development database, remove:

```text
var/shanakht.sqlite3
```

Then recreate it:

```powershell
python main.py migrate
```

If model assets need to be reacquired, remove only the relevant local model directory and rerun:

```powershell
python main.py warm_ocr_models --allow-download
```

Do **not** delete production databases or production identity-document storage as part of a local reset procedure.

---

# 24. Stopping the Application

Django and Vite run in separate terminals.

To stop either development server:

```text
Ctrl + C
```

Stop:

1. Frontend terminal
2. Backend terminal

The local SQLite database and model files remain available for the next session.

---

# 25. Useful URLs

| URL                                      | Purpose               |
| ---------------------------------------- | --------------------- |
| `http://localhost:5173/`                 | Frontend landing page |
| `http://localhost:5173/auth`             | Authentication        |
| `http://localhost:5173/app`              | Applicant dashboard   |
| `http://localhost:5173/app/new/document` | CNIC upload           |
| `http://localhost:5173/app/new/selfie`   | Selfie capture        |
| `http://localhost:5173/app/new/liveness` | Liveness workflow     |
| `http://localhost:5173/app/new/review`   | Review and submission |
| `http://localhost:5173/admin`            | Admin dashboard       |
| `http://localhost:5173/admin/review`     | Reviewer queue        |
| `http://localhost:5173/admin/api`        | API key management    |
| `http://127.0.0.1:8000/admin/`           | Django Admin          |
| `http://127.0.0.1:8000/api/docs/`        | Swagger UI            |
| `http://127.0.0.1:8000/api/schema/`      | OpenAPI schema        |
| `http://127.0.0.1:8000/health/live`      | Liveness              |
| `http://127.0.0.1:8000/health/ready`     | Readiness             |

---

# 26. Development vs Production

This guide is primarily intended for **local development and testing**.

## Local Development

The default profile can use:

```text
SQLite
Django development server
Vite development server
local filesystem
eager/background task fallback
CPU inference
```

## Production

A production deployment should generally use:

```text
PostgreSQL
Redis
background workers
private object storage
TLS
reverse proxy
secret management
monitoring
scheduled retention cleanup
restricted administrative access
```

Do not expose Django's development server directly to the public internet.

Do not use development secrets in production.

Do not use public storage for identity documents.

---

# 27. Final Verification Checklist

Before considering the local installation ready:

### Environment

```text
[ ] Python 3.11 installed
[ ] Node.js 22 installed
[ ] npm 10 installed
[ ] Virtual environment created
[ ] Backend dependencies installed
[ ] Frontend dependencies installed
```

### Configuration

```text
[ ] .env created
[ ] KYC_SECRET_KEY configured
[ ] KYC_API_KEYS configured
[ ] Frontend .env created
[ ] CSRF trusted origins configured
```

### Database

```text
[ ] Migrations completed
[ ] Django system check passes
[ ] Admin account created
```

### Models

```text
[ ] EasyOCR models downloaded/prepared
[ ] Model manifest loads successfully
[ ] Readiness endpoint returns 200
```

### Application

```text
[ ] Django running on 127.0.0.1:8000
[ ] Vite running on localhost:5173
[ ] Frontend loads
[ ] Authentication works
[ ] Swagger loads
[ ] API authentication works
```

### KYC Workflow

```text
[ ] Applicant can sign in
[ ] Application can be created
[ ] Front image can be uploaded
[ ] Back image can be uploaded
[ ] Selfie workflow works
[ ] Liveness workflow works or routes to review
[ ] Consent can be recorded
[ ] Application can be submitted
[ ] Results page loads
```

### Administration

```text
[ ] Admin can sign in
[ ] Applications are visible
[ ] Review queue works
[ ] Reviewer workspace loads
[ ] OCR correction workflow works
[ ] Decision workflow works
[ ] API key management works
```

### Testing

```text
[ ] Backend tests pass
[ ] Frontend tests pass
[ ] Frontend production build succeeds
[ ] Liveness endpoint passes
[ ] Readiness endpoint passes
```

---

# 🔐 Important Security Reminder

Shanakht processes highly sensitive identity information.

Never use real CNICs, selfies, or production identity data for casual development, screenshots, demonstrations, debugging, or public issue reports unless the data has been appropriately authorized and protected.

For development and automated testing, prefer:

* synthetic documents
* generated image fixtures
* redacted examples
* test accounts
* non-production API keys
* isolated development storage

Before deploying the system for real KYC processing, perform an appropriate security, privacy, legal, and operational review.

---

# 🚀 Quick Start

For experienced developers, the shortest local setup is:

```powershell
# 1. Python environment
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.lock

# 3. Environment
Copy-Item .env.example .env

# 4. Generate secrets
python -c "import secrets; print('SECRET_KEY:', secrets.token_urlsafe(64)); print('API_KEY:', secrets.token_urlsafe(32))"

# 5. Database
python main.py migrate
python main.py check

# 6. OCR
python main.py warm_ocr_models --allow-download
python main.py model_manifest

# 7. Admin
python main.py bootstrap_shanakht --username Shawaiz --email shawaiz.datascience@gmail.com

# 8. Backend
python ".\Django Api\manage.py" runserver 127.0.0.1:8000
```

In another terminal:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Then open:

```text
Frontend:
http://localhost:5173

Swagger:
http://127.0.0.1:8000/api/docs/

Django Admin:
http://127.0.0.1:8000/admin/

Health:
http://127.0.0.1:8000/health/live
```

---

## 📌 Documentation Status

This document describes the **local development and testing workflow** for Shanakht.

For deployment-specific procedures, model provenance, API contracts, benchmark methodology, security controls, and implementation status, refer to the corresponding documentation under:

```text
docs/
```

The `.env` file, runtime `var/` directory, uploaded identity documents, evaluation datasets, and model weights must be provisioned separately on each development or deployment environment.
