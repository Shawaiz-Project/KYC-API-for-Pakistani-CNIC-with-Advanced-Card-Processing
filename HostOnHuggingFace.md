# Hosting Shanakht on Hugging Face Spaces

> **Approach:** Deploy the Django API (+ React frontend served as static files) as a single **Docker Space** on Hugging Face.  
> **Why Docker Space?** The project uses PyTorch, EasyOCR, OpenCV, and Gunicorn — a standard Gradio/Streamlit SDK cannot serve it.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Architecture Overview](#2-architecture-overview)
3. [Step 1 — Create the Hugging Face Space](#3-step-1--create-the-hugging-face-space)
4. [Step 2 — Create the HF-specific Dockerfile](#4-step-2--create-the-hf-specific-dockerfile)
5. [Step 3 — Create the Startup Script](#5-step-3--create-the-startup-script)
6. [Step 4 — Build the React Frontend](#6-step-4--build-the-react-frontend)
7. [Step 5 — Space README.md YAML Header](#7-step-5--space-readmemd-yaml-header)
8. [Step 6 — Set Secrets in Space Settings](#8-step-6--set-secrets-in-space-settings)
9. [Step 7 — Push to Hugging Face](#9-step-7--push-to-hugging-face)
10. [Step 8 — Verify the Deployment](#10-step-8--verify-the-deployment)
11. [Step 9 — Create the Admin Account](#11-step-9--create-the-admin-account)
12. [Persistent Storage (Optional Upgrade)](#12-persistent-storage-optional-upgrade)
13. [Limitations & Known Constraints](#13-limitations--known-constraints)

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| Hugging Face account | Free account works; Docker Spaces may require **PRO** plan for CPU compute |
| `git` | With **Git LFS** installed (`git lfs install`) |
| Docker Desktop | For local testing before push |
| Python 3.11 + venv | To build the React frontend locally |
| Node.js 22 + npm | To build the React frontend locally |

> Install Git LFS: https://git-lfs.com  
> Sign up for HF: https://huggingface.co/join

---

## 2. Architecture Overview

Hugging Face Spaces runs a **single container** — `docker-compose` with multiple services is **not** supported. The deployment adapts the project to a single-process model:

```
HF Docker Space (port 7860)
│
├── gunicorn (Django API on 0.0.0.0:7860)
│   ├── api/v1/kyc/process      ← CNIC upload endpoint
│   ├── api/v2/...              ← Full application API
│   ├── api/docs/               ← Swagger UI
│   └── /static/ + /           ← React frontend (whitenoise)
│
├── SQLite (var/shanakht.sqlite3) ← ephemeral in free tier
├── EasyOCR models (var/models/)  ← downloaded on first startup
└── Private uploads (var/private-kyc/) ← ephemeral in free tier
```

**Trade-offs vs full docker-compose:**
- ✅ SQLite replaces PostgreSQL (built-in, no extra service needed)
- ✅ `KYC_TASK_ALWAYS_EAGER=true` replaces Celery + Redis (tasks run inline)
- ✅ React app is served as static files via WhiteNoise (no nginx needed)
- ⚠️ Storage is **ephemeral** unless you attach an HF Storage Bucket (see [Section 12](#12-persistent-storage-optional-upgrade))
- ⚠️ EasyOCR models download on first startup (~200 MB, takes ~2–3 min)

---

## 3. Step 1 — Create the Hugging Face Space

1. Go to **https://huggingface.co/new-space**
2. Fill in the form:
   - **Space name:** `shanakht-kyc` (or your preferred name)
   - **License:** Choose your license (e.g., MIT)
   - **SDK:** Select **Docker**
   - **Visibility:** Set to **Private** (required for identity document handling)
3. Click **Create Space**

This creates a Git repository at:
```
https://huggingface.co/spaces/<your-username>/shanakht-kyc
```

---

## 4. Step 2 — Create the HF-specific Dockerfile

Create a new file **`Dockerfile.hf`** in your project root. This is the Hugging Face variant — it runs everything in a single process on port 7860.

```dockerfile
# Dockerfile.hf — Hugging Face Spaces single-container deployment
FROM python:3.11.9-slim-bookworm

# Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=api.settings \
    KYC_DATABASE_ENGINE=sqlite \
    KYC_SQLITE_PATH=/data/shanakht.sqlite3 \
    KYC_PRIVATE_STORAGE_ROOT=/data/private-kyc \
    KYC_OBJECT_STORAGE_ROOT=/data/private-objects \
    KYC_OCR_MODEL_DIR=/data/models/easyocr \
    KYC_TASK_ALWAYS_EAGER=true \
    KYC_DEBUG=false \
    KYC_DEVICE=cpu \
    KYC_OCR_DOWNLOAD_ENABLED=true \
    PORT=7860

# System dependencies for OpenCV + EasyOCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libgl1 libgomp1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY Requirements.txt ./
RUN python -m pip install --upgrade pip && \
    python -m pip install -r Requirements.txt

# Copy Django backend
COPY ["Django Api", "/app/Django Api"]

# Copy the pre-built React frontend static files
# (You must run `npm run build` locally before pushing)
COPY ["frontend/dist", "/app/Django Api/staticfiles_src/frontend"]

# Set the working directory to Django project
WORKDIR "/app/Django Api"

# Collect static files (Django + React)
RUN KYC_SECRET_KEY=build-only-placeholder python manage.py collectstatic --noinput

# Create data directories and set permissions
# HF Spaces runs as UID 1000
RUN mkdir -p /data/private-kyc /data/private-objects /data/models && \
    chown -R 1000:1000 /data /app

# Copy startup script
COPY hf_startup.sh /app/hf_startup.sh
RUN chmod +x /app/hf_startup.sh && chown 1000:1000 /app/hf_startup.sh

USER 1000

EXPOSE 7860

CMD ["/app/hf_startup.sh"]
```

---

## 5. Step 3 — Create the Startup Script

Create **`hf_startup.sh`** in your project root:

```bash
#!/bin/bash
# hf_startup.sh — Runs migrations, warms OCR models, then starts gunicorn

set -e

cd "/app/Django Api"

echo "==> Running database migrations..."
python manage.py migrate --noinput

echo "==> Warming EasyOCR model weights (may take 2-3 min on first run)..."
python manage.py warm_ocr_models

echo "==> Running system check..."
python manage.py check

echo "==> Starting gunicorn on port ${PORT:-7860}..."
exec gunicorn api.wsgi:application \
    --bind "0.0.0.0:${PORT:-7860}" \
    --workers 2 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile -
```

---

## 6. Step 4 — Build the React Frontend

The frontend must be **pre-built** and included in the Docker image because HF Spaces doesn't run `npm`.

### Configure the frontend API base URL

Edit **`frontend/.env`** (create from `.env.example` if needed):

```dotenv
# Point to the same origin — Django serves both API and frontend
VITE_API_BASE=/api/v2
VITE_DEMO_MODE=false
```

### Build the frontend

```powershell
# From project root
Set-Location frontend
npm ci
npm run build
Set-Location ..
```

This creates `frontend/dist/` which the Dockerfile copies into the image.

### Wire React static files into Django

Add this to the end of **`Django Api/api/settings.py`** (before `INSTALLED_APPS` is closed):

```python
# Serve the pre-built React frontend from /
WHITENOISE_ROOT = BASE_DIR / "staticfiles_src" / "frontend"
```

And verify `whitenoise.middleware.WhiteNoiseMiddleware` is in `MIDDLEWARE` (it already is in the project).

> **Note:** The React app is already set to use `/api/v2` as its base, so routing works seamlessly when served from the same Django origin.

---

## 7. Step 5 — Space README.md YAML Header

When you push to your HF Space repo, the `README.md` at the root must have this YAML frontmatter so HF knows it's a Docker space on port 7860:

```markdown
---
title: Shanakht KYC API
emoji: 🪪
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
app_file: Dockerfile.hf
suggested_hardware: cpu-basic
pinned: false
---

# Shanakht — Pakistani CNIC KYC API

A privacy-conscious KYC API and reviewer interface for Pakistani CNIC documents.

- Upload CNIC front + back images for OCR extraction
- Structured field validation (CNIC 5-7-1 syntax, date checks)
- Admin reviewer workspace
- Interactive API docs at `/api/docs/`

> This Space processes identity documents. Keep it **Private**.
```

---

## 8. Step 6 — Set Secrets in Space Settings

Go to your Space → **Settings tab** → **Repository secrets** section.

Add each secret as a **Secret** (not a variable) so values stay private:

| Secret Name | Value | Notes |
|---|---|---|
| `KYC_SECRET_KEY` | Output of `python -c "import secrets; print(secrets.token_urlsafe(64))"` | Must be 50+ chars |
| `KYC_API_KEYS` | Output of `python -c "import secrets; print(secrets.token_urlsafe(32))"` | Your API bearer key |
| `KYC_ALLOWED_HOSTS` | `<your-username>-shanakht-kyc.hf.space` | Your exact HF Space hostname |
| `KYC_CSRF_TRUSTED_ORIGINS` | `https://<your-username>-shanakht-kyc.hf.space` | For browser CSRF |
| `KYC_SECURE_SSL_REDIRECT` | `false` | HF terminates TLS |
| `KYC_SESSION_COOKIE_SECURE` | `true` | HTTPS cookie flag |
| `KYC_CSRF_COOKIE_SECURE` | `true` | HTTPS cookie flag |
| `KYC_TRUST_PROXY_SSL_HEADER` | `true` | HF proxies HTTPS |
| `KYC_LOG_LEVEL` | `INFO` | |
| `KYC_PRESERVE_UPLOADS` | `true` | |
| `KYC_RETENTION_HOURS` | `24` | Auto-cleanup after 24h |

> **Finding your Space hostname:** It follows the pattern `https://<username>-<space-name>.hf.space`  
> Example: `https://shawaiz-shanakht-kyc.hf.space`

---

## 9. Step 7 — Push to Hugging Face

### Clone your HF Space repository

```bash
# Install Git LFS first if not already done
git lfs install

# Clone the empty Space repo
git clone https://huggingface.co/spaces/<your-username>/shanakht-kyc
cd shanakht-kyc
```

### Copy your project files into the Space repo

Copy these files/folders from your project into the cloned Space directory:

```
shanakht-kyc/
├── Dockerfile.hf          ← The HF-specific Dockerfile (from Step 2)
├── hf_startup.sh          ← Startup script (from Step 3)
├── Requirements.txt       ← Python dependencies
├── README.md              ← With YAML header (from Step 5)
├── Django Api/            ← Full Django backend
└── frontend/
    └── dist/              ← Pre-built React app (from Step 4)
```

> **Do NOT copy** `.env`, `.venv/`, `var/`, `Dataset/`, `*.onnx`, `*.pt`

### Push

```bash
git add .
git commit -m "feat: initial Hugging Face Spaces deployment"
git push origin main
```

HF will automatically detect `Dockerfile.hf` (from the `app_file` in README YAML), build the image, and start the container.

> **Build time:** First build takes **5–10 minutes** (installing PyTorch, EasyOCR dependencies).  
> **First startup:** ~2–3 additional minutes for EasyOCR model download.

### Monitor the build

Go to your Space page → click **"Logs"** tab to watch the build and startup output in real time.

---

## 10. Step 8 — Verify the Deployment

Once the Space shows **"Running"**, test these URLs:

```bash
# Replace with your actual Space URL
BASE=https://<your-username>-shanakht-kyc.hf.space

# 1. Liveness check
curl $BASE/health/live

# 2. Readiness check (wait for 200 — models may still be warming up)
curl $BASE/health/ready

# 3. Interactive Swagger API docs (open in browser)
echo "Open: $BASE/api/docs/"

# 4. React frontend (open in browser)
echo "Open: $BASE/"

# 5. Test a CNIC upload
curl -X POST $BASE/api/v1/kyc/process \
  -H "X-API-Key: <your KYC_API_KEYS value>" \
  -H "X-Request-ID: hf-test-001" \
  -F "front=@/path/to/cnic_front.jpg" \
  -F "back=@/path/to/cnic_back.jpg" \
  -F "template=auto"
```

---

## 11. Step 9 — Create the Admin Account

After the Space is running, use the HF Space **"App" tab** terminal (if available on your plan), or add a one-time management command. The easiest way for HF Spaces:

### Option A — Via the Space terminal (HF PRO)

In the Space → **"App" tab** → open terminal:

```bash
cd "/app/Django Api"
python manage.py bootstrap_shanakht --username admin --email your@email.com
```

### Option B — Via a temporary management endpoint

Add a `POST /api/v2/admin/bootstrap` endpoint protected by `KYC_API_KEYS`, call it once, then disable it. See `Django Api/detector/management/` for the existing `bootstrap_shanakht` command as reference.

### Option C — Via Django Admin with a custom fixture

```bash
# Locally, create a fixture:
python manage.py dumpdata auth.user --indent 2 > users.json
# Push users.json to the Space and load it:
python manage.py loaddata users.json
```

---

## 12. Persistent Storage (Optional Upgrade)

By default, HF Spaces disk is **ephemeral** — the SQLite database and uploaded images are lost on restart.

### Attach an HF Storage Bucket

1. Go to your Space → **Settings** → **"Storage Buckets"** section
2. Click **"Attach Storage Bucket"** and create a new bucket
3. Set the mount path to `/data`

With `/data` persisted:
- `KYC_SQLITE_PATH=/data/shanakht.sqlite3` → database survives restarts
- `KYC_PRIVATE_STORAGE_ROOT=/data/private-kyc` → uploads survive restarts
- `KYC_OCR_MODEL_DIR=/data/models/easyocr` → models only download once

> **Cost:** HF Storage Buckets are a paid feature. Check current pricing at https://huggingface.co/pricing

### Model pre-caching

To avoid the 2–3 minute cold-start model download, pre-download the EasyOCR weights and commit them to your Space repo using **Git LFS**:

```bash
# Download locally
python main.py warm_ocr_models --allow-download

# Track with Git LFS (files are .pth / .pt)
git lfs track "*.pth"
git lfs track "*.pt"
git add .gitattributes var/models/
git commit -m "feat: pre-cache EasyOCR model weights via Git LFS"
git push
```

Then update `hf_startup.sh` to skip the download step:
```bash
echo "==> Warming EasyOCR model weights (pre-cached)..."
python manage.py warm_ocr_models  # No --allow-download flag
```

---

## 13. Limitations & Known Constraints

| Limitation | Details | Workaround |
|---|---|---|
| **Ephemeral storage** | SQLite DB + uploads lost on restart | Attach HF Storage Bucket to `/data` |
| **No Redis / Celery** | Background tasks run inline (`TASK_ALWAYS_EAGER=true`) | Acceptable for demo; use Redis addon for production |
| **No PostgreSQL** | Uses SQLite | Good for single-user demo; attach external DB for production |
| **Cold start delay** | EasyOCR downloads ~200 MB on first boot | Pre-cache models via Git LFS |
| **CPU only** | GPU inference disabled by default | Select GPU hardware tier in Space Settings |
| **Single worker** | 2 Gunicorn workers share the same process | Enough for demo; scale via HF hardware tiers |
| **No NADRA** | Authoritative CNIC verification unavailable | Expected; system only does OCR + local checks |
| **Private Space required** | Identity documents must never be public | Set Visibility = Private when creating Space |
| **Liveness check** | Routes to manual review without anti-spoof ONNX model | Expected in this deployment |
| **Face comparison** | Unavailable without `yunet.onnx` + `sface.onnx` models | Commit models to repo or download at startup |

---

## Quick Reference

| URL | What it is |
|---|---|
| `https://<username>-<space>.hf.space/` | React frontend (sign in, submit CNIC) |
| `https://<username>-<space>.hf.space/auth` | Sign in page |
| `https://<username>-<space>.hf.space/admin` | Admin/reviewer dashboard |
| `https://<username>-<space>.hf.space/api/docs/` | Swagger interactive API docs |
| `https://<username>-<space>.hf.space/api/v1/kyc/process` | v1 CNIC upload endpoint |
| `https://<username>-<space>.hf.space/health/live` | Liveness probe |
| `https://<username>-<space>.hf.space/health/ready` | Readiness probe (200 = models loaded) |
| `https://<username>-<space>.hf.space/admin/` (trailing slash) | Django admin panel |

---

*This guide is specific to the Hugging Face Spaces Docker environment. For full production deployment with PostgreSQL, Redis, S3, and Celery, see `docs/deployment.md`.*
