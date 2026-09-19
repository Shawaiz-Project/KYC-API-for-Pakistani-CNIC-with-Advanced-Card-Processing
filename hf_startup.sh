#!/bin/bash
# hf_startup.sh — Hugging Face Spaces startup script for Shanakht KYC
# Runs on every container start: migrates DB, warms OCR models, then serves.

set -e

DJANGO_DIR="/app/Django Api"

echo "=== Shanakht KYC — Hugging Face Spaces Startup ==="
echo "Working directory: $DJANGO_DIR"

cd "$DJANGO_DIR"

echo ""
echo "==> [1/4] Running database migrations..."
python manage.py migrate --noinput

echo ""
echo "==> [2/4] Warming EasyOCR model weights..."
echo "    First run downloads ~200 MB from easyocr.jaided.ai — this takes 2-3 minutes."
echo "    Subsequent starts use cached weights in KYC_OCR_MODEL_DIR."
python manage.py warm_ocr_models

echo ""
echo "==> [3/4] Running system check..."
python manage.py check

echo ""
echo "==> [4/4] Starting Gunicorn on port ${PORT:-7860}..."
exec gunicorn api.wsgi:application \
    --bind "0.0.0.0:${PORT:-7860}" \
    --workers 2 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile -
