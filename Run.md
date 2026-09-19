# Shanakht — KYC API for Pakistani CNIC: Run Guide

> **Project name:** Shanakht &nbsp;|&nbsp; **Stack:** Django 4 + React/TypeScript (Vite) + SQLite (dev)  
> **Purpose:** Upload, process, and review Pakistani CNIC images via OCR and detector checks.

---

## Table of Contents

1. [Requirements](#1-requirements)
2. [First-Time Setup](#2-first-time-setup)
3. [Generate Secrets & Update `.env`](#3-generate-secrets--update-env)
4. [Initialize the Database & Models](#4-initialize-the-database--models)
5. [Create the Admin Account](#5-create-the-admin-account)
6. [Run the Servers](#6-run-the-servers)
7. [Client Flow — Upload CNIC Images (Web UI)](#7-client-flow--upload-cnic-images-web-ui)
8. [Admin Flow — Review Applications (Web UI)](#8-admin-flow--review-applications-web-ui)
9. [Direct API Testing — Upload CNIC via curl / Swagger](#9-direct-api-testing--upload-cnic-via-curl--swagger)
10. [Run Automated Tests](#10-run-automated-tests)
11. [Health Checks](#11-health-checks)
12. [Useful URLs at a Glance](#12-useful-urls-at-a-glance)

---

## 1. Requirements

| Requirement | Version |
|---|---|
| Python (CPython) | 3.11.x |
| Node.js | 22.x |
| npm | 10.x |
| OS | Windows 10/11 or Linux |
| RAM | >= 4 GB (EasyOCR model weights load into memory) |

> **Windows extra:** Install [Microsoft Visual C++ 2019+ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) for ONNX Runtime.

---

## 2. First-Time Setup

### Backend (Python virtual environment)

Open **PowerShell** in the project root:

```powershell
# Create virtual environment with Python 3.11
py -3.11 -m venv .venv

# Activate it
.\.venv\Scripts\Activate.ps1

# Upgrade pip and install all locked dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
```

### Frontend (Node.js)

```powershell
Set-Location frontend
npm ci                        # Install exact dependency versions
Copy-Item .env.example .env   # Copy frontend environment file
Set-Location ..               # Return to project root
```

---

## 3. Generate Secrets & Update `.env`

The `.env` file in the project root controls all server settings.  
**The server refuses to start with the placeholder example values.**

### Generate fresh secrets

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print('SECRET_KEY:', secrets.token_urlsafe(64)); print('API_KEY:', secrets.token_urlsafe(32))"
```

Example output:
```
SECRET_KEY: u6epkRugPKZVDS2a_zjMxW2rPNSi79_tx5P-zW1...
API_KEY:    2lnm3RpVv3GjLHZQ7cBl9F1UzIsY7czBE2UJXMAC_cM
```

### Edit `.env`

Open `.env` and replace **at minimum** these two lines:

```dotenv
KYC_SECRET_KEY=<paste SECRET_KEY value here>
KYC_API_KEYS=<paste API_KEY value here>
```

> Keep `KYC_DEBUG=true` during local development.  
> The API key in `KYC_API_KEYS` is what you send as the `X-API-Key` header in all API requests.

---

## 4. Initialize the Database & Models

Run these commands once (from the project root with the venv active):

```powershell
# Apply database migrations (creates SQLite at var/shanakht.sqlite3)
.\.venv\Scripts\python.exe main.py migrate

# Verify the configuration is valid
.\.venv\Scripts\python.exe main.py check

# Download and warm EasyOCR model weights (first run only -- downloads ~200 MB)
.\.venv\Scripts\python.exe main.py warm_ocr_models --allow-download

# Print the loaded model manifest for confirmation
.\.venv\Scripts\python.exe main.py model_manifest
```

> **Offline systems:** Copy pre-downloaded weights to `./var/models/easyocr/` and run `warm_ocr_models` **without** `--allow-download`.

---

## 5. Create the Admin Account

```powershell
.\.venv\Scripts\python.exe main.py bootstrap_shanakht --username Shawaiz --email shawaiz.datascience@gmail.com
```

You will be prompted to enter and confirm a password interactively.  
This creates the first admin user who can sign in at the web UI and access Django admin.

---

## 6. Run the Servers

### Terminal 1 — Backend (Django)

```powershell
# From project root, with .venv active:
.\.venv\Scripts\python.exe "Django Api\manage.py" runserver 127.0.0.1:8000
```

Expected output:
```
Watching for file changes with StatReloader
System check identified no issues (0 silenced).
Starting development server at http://127.0.0.1:8000/
```

### Terminal 2 — Frontend (Vite + React)

```powershell
# From the frontend/ directory:
Set-Location frontend
npm run dev
```

Expected output:
```
  VITE v7.x  ready in ~2000 ms
  Local:   http://localhost:5173/
```

---

## 7. Client Flow — Upload CNIC Images (Web UI)

The **client (applicant)** submits their CNIC through a 4-step wizard at `http://localhost:5173`.

### Step 1 — Sign In as Applicant

1. Open **http://localhost:5173/auth**
2. Enter your email and password
3. Applicants land on `/app` (the Applicant Home dashboard)

> An admin must create applicant accounts via Django Admin at `http://127.0.0.1:8000/admin/`

### Step 2 — Start a New Application

1. On the Applicant Home (`/app`), click **"Start new verification"**
2. A new `KycApplication` record is created automatically

### Step 3 — Upload CNIC Front & Back (`/app/new/document`)

1. You see two upload cards: **Front side** and **Back side**
2. Click **"Upload image"** on each card
3. Select a **JPG, PNG, or WebP** photo of the CNIC

**Guidelines for a good upload:**
- Use the **original physical card** (no screen photos)
- Keep all **4 edges visible**
- Avoid **reflections and glare**
- Maximum **10 MB** per image
- Minimum resolution: **640 x 400 px**
- The card should fill at least **12% of the image area**

4. A green strip appears: *"Image decoded and ready for server quality checks"*
5. Click **"Continue to selfie"**

### Step 4 — Selfie Capture (`/app/new/selfie`)

1. Click **"Open camera"** to use webcam, or **"Upload image"** for a file
2. Face the camera with a neutral expression and even lighting
3. Remove sunglasses and hats; only one face allowed
4. Click **"Capture photo"** or upload a selfie file
5. Click **"Continue to liveness"**

### Step 5 — Liveness Check (`/app/new/liveness`)

1. Click **"Start challenge"** to receive a server-issued randomized challenge
2. Follow the on-screen actions (e.g., *turn left, turn right, look center*)
3. Alternatively, click **"Use manual review route"** to skip to a human reviewer

> **Note:** Without a deployed anti-spoofing ONNX model, liveness automatically routes to manual review. This is expected for local development.

### Step 6 — Review & Submit (`/app/new/review`)

1. Review your uploaded images (front, back, selfie previews)
2. Check the **consent checkbox**: *"I consent to processing my documents and selfie for this verification"*
3. Click **"Submit application"**
4. You are redirected to the **Results page** (`/app/results/<id>`)

### Step 7 — View Results (`/app/results/<id>`)

The results page shows:

| Section | Details |
|---|---|
| **Outcome badge** | `checks_passed` / `needs_review` / `needs_recapture` / `checks_failed` |
| **Check results** | Each detector's status, score, reason codes, model version, and execution time |
| **Extracted fields** | OCR-extracted name, CNIC number, date of birth, expiry, etc. |
| **Official verification** | Always `unavailable` unless NADRA integration is configured |

---

## 8. Admin Flow — Review Applications (Web UI)

### Sign In as Admin

1. Open **http://localhost:5173/auth**
2. Enter admin credentials created in [Step 5](#5-create-the-admin-account)
3. Admins automatically land on `/admin` (Admin Overview dashboard)

### View All Applications (`/admin/applications`)

- Full table of all submitted applications with status badges
- Click any row to open the Reviewer Workspace

### Review Queue (`/admin/review`)

- Filtered view: applications with `needs_review` or `checks_failed` outcome
- Route uncertain applications to a reviewer from here

### Reviewer Workspace (`/admin/review/<id>`)

The workspace has two panels:

**Left panel — Evidence:**
- **Private source media:** Protected thumbnails of uploaded front, back, and selfie images
- **Check evidence:** Each detector's name, status badge, reason codes, and model version

**Right panel — Decisions:**
- **Extracted information:** OCR fields with raw and normalized values
- **Correct OCR:** Enter a field name, corrected value, and reason → click **"Save revision"**
- **Decision actions:**
  - ✅ **"Approve checks"** → outcome = `checks_passed`
  - ⚠️ **"Request recapture"** → outcome = `needs_recapture`
  - ❌ **"Fail checks"** → outcome = `checks_failed`

### Manage API Keys (`/admin/api`)

- Create scoped API keys for integration clients
- Set name, quota per minute, scopes (`applications:read`, `applications:write`)
- **Copy the key immediately** — it is shown only once
- Rotate or revoke existing keys

### Django Admin Panel (`http://127.0.0.1:8000/admin/`)

- Create and manage users and organizations
- Assign roles: `admin`, `reviewer`, `applicant`, `api_client`
- View application records and audit events

---

## 9. Direct API Testing — Upload CNIC via curl / Swagger

### Method A: Swagger UI (easiest for manual testing)

1. Open **http://127.0.0.1:8000/api/docs/**
2. Click **"Authorize"** → enter your API key from `.env` (`KYC_API_KEYS`)
3. Expand **`POST /api/v1/kyc/process`**
4. Click **"Try it out"**
5. Upload `front` and `back` image files, set `template` to `auto`
6. Click **"Execute"** and view the structured JSON response

### Method B: curl (PowerShell)

```powershell
# Set your API key
$API_KEY = "2lnm3RpVv3GjLHZQ7cBl9F1UzIsY7czBE2UJXMAC_cM"

# Process a CNIC pair
curl.exe -X POST http://127.0.0.1:8000/api/v1/kyc/process `
  -H "X-API-Key: $API_KEY" `
  -H "X-Request-ID: test-run-001" `
  -F "front=@C:\path\to\cnic_front.jpg" `
  -F "back=@C:\path\to\cnic_back.jpg" `
  -F "template=auto"
```

#### Template options

| Value | Description |
|---|---|
| `auto` | Auto-detect CNIC format (recommended default) |
| `smart` | Smart extraction |
| `smart_card` | Smart extraction with card-aware layout |
| `nicop` | Pakistani NICOP (overseas format) |
| `generic` | Generic OCR without CNIC-specific parsing |
| `legacy_urdu` | Legacy Urdu-first extraction |

### Method C: Legacy endpoint (backward compatible)

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/card/detector `
  -H "X-API-Key: $API_KEY" `
  -F "front_imagee=@C:\path\to\cnic_front.jpg" `
  -F "back_image=@C:\path\to\cnic_back.jpg"
```

> Note the intentional typo `front_imagee` in the legacy endpoint — retained for backward compatibility.

### v2 API (session-authenticated, admin only)

The Phase 3 v2 endpoints use browser session cookies (CSRF). Use the Swagger UI at `/api/docs/` or the React frontend.

```
GET  /api/v2/applications                          # List all applications
GET  /api/v2/applications/<id>                     # Application detail with checks & artifacts
POST /api/v2/applications                          # Create new application
POST /api/v2/applications/<id>/artifacts           # Upload front/back/selfie
POST /api/v2/applications/<id>/consent             # Give consent
POST /api/v2/applications/<id>/submit              # Submit for processing
POST /api/v2/applications/<id>/decisions           # Admin: approve/reject/recapture
POST /api/v2/applications/<id>/corrections         # Admin: correct an OCR field
POST /api/v2/applications/<id>/assignment          # Assign to a reviewer
GET  /api/v2/auth/me                               # Current user info
POST /api/v2/auth/sign-in                          # Sign in
POST /api/v2/auth/sign-out                         # Sign out
```

---

## 10. Run Automated Tests

### Backend tests

```powershell
# From project root (venv active)
.\.venv\Scripts\python.exe main.py test -v 2
```

All test images are generated **in memory** — no real identity documents are needed.

Tests cover:
- Content validation, corruption, size, format limits
- EXIF orientation, card rotation, missing/multiple/incomplete cards
- Quality gates (blur, exposure, glare)
- Unicode/Urdu text ordering
- OCR parsing and field validation
- Auth, throttling, error responses
- Storage concurrency and retention

### Frontend tests

```powershell
Set-Location frontend
npm test           # Unit tests (Vitest)
npm run build      # Verify the production build compiles without errors
```

---

## 11. Health Checks

```powershell
# Liveness -- Django can serve requests (200 = OK)
curl.exe http://127.0.0.1:8000/health/live

# Readiness -- all required models loaded (200 = OK, 503 = not ready)
curl.exe http://127.0.0.1:8000/health/ready
```

If `/health/ready` returns **503**, the JSON body explains which components are not ready (secrets missing, private storage unreachable, or model weights not downloaded).

---

## 12. Useful URLs at a Glance

| URL | What it is |
|---|---|
| http://localhost:5173 | Landing page |
| http://localhost:5173/auth | Sign in |
| http://localhost:5173/app | Applicant dashboard |
| http://localhost:5173/app/new/document | Upload CNIC front & back |
| http://localhost:5173/app/new/selfie | Selfie capture |
| http://localhost:5173/app/new/liveness | Liveness challenge |
| http://localhost:5173/app/new/review | Review & submit |
| http://localhost:5173/admin | Admin overview |
| http://localhost:5173/admin/review | Reviewer queue |
| http://localhost:5173/admin/api | API key management |
| http://127.0.0.1:8000/admin/ | Django admin panel |
| http://127.0.0.1:8000/api/docs/ | Swagger interactive API docs |
| http://127.0.0.1:8000/api/schema/ | OpenAPI schema (JSON/YAML) |
| http://127.0.0.1:8000/health/live | Liveness probe |
| http://127.0.0.1:8000/health/ready | Readiness probe |

---

## Common Issues

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'drf_spectacular'` | Activate the venv: `.\.venv\Scripts\Activate.ps1` then retry |
| Server rejects `KYC_SECRET_KEY` or `KYC_API_KEYS` | Replace the placeholder values in `.env` with freshly generated secrets |
| API returns 401 Unauthorized | Pass `-H "X-API-Key: <key>"` matching `KYC_API_KEYS` in `.env` |
| `/health/ready` returns 503 | Run `warm_ocr_models --allow-download` to download EasyOCR model weights |
| CSRF errors from frontend | Add `http://localhost:5173` to `KYC_CSRF_TRUSTED_ORIGINS` in `.env` |
| `RuntimeError: Script main.py does not exist` | Use manage.py directly: `.\.venv\Scripts\python.exe "Django Api\manage.py" runserver` |
| Images fail quality gate (blur / glare / exposure) | Use a well-lit environment; card must fill >= 12% of frame; minimum 640x400 px |
| Image rejected as "wrong side" | Confirm front image is the side with the photo and name, back has the fingerprint |

---

*This file was generated to document the local development run procedure for the Shanakht KYC project. The `.env` file, `var/` directory, and model weights are git-ignored and must be re-created locally on each machine.*
