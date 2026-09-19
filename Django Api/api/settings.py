"""Environment-driven Django settings for the CNIC KYC API."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = BASE_DIR.parent
load_dotenv(REPOSITORY_ROOT / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def env_path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default)).expanduser()
    return value if value.is_absolute() else (REPOSITORY_ROOT / value).resolve()


DEBUG = env_bool("KYC_DEBUG", False)
SECRET_KEY = os.getenv("KYC_SECRET_KEY", "") or "development-only-unconfigured-key"
ALLOWED_HOSTS = env_list("KYC_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
SECURE_SSL_REDIRECT = env_bool("KYC_SECURE_SSL_REDIRECT", False)
SESSION_COOKIE_SECURE = env_bool("KYC_SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("KYC_CSRF_COOKIE_SECURE", False)
CSRF_TRUSTED_ORIGINS = env_list(
    "KYC_CSRF_TRUSTED_ORIGINS",
    "http://127.0.0.1:5173,http://localhost:5173",
)
SECURE_HSTS_SECONDS = env_int("KYC_SECURE_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("KYC_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("KYC_SECURE_HSTS_PRELOAD", False)
if env_bool("KYC_TRUST_PROXY_SSL_HEADER", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "detector",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "detector.middleware.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "api.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
WSGI_APPLICATION = "api.wsgi.application"
ASGI_APPLICATION = "api.asgi.application"

_database_engine = os.getenv("KYC_DATABASE_ENGINE", "sqlite").strip().lower()
if _database_engine == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("KYC_DATABASE_NAME", "shanakht"),
            "USER": os.getenv("KYC_DATABASE_USER", "shanakht"),
            "PASSWORD": os.getenv("KYC_DATABASE_PASSWORD", ""),
            "HOST": os.getenv("KYC_DATABASE_HOST", "127.0.0.1"),
            "PORT": env_int("KYC_DATABASE_PORT", 5432),
            "CONN_MAX_AGE": env_int("KYC_DATABASE_CONN_MAX_AGE", 60),
        }
    }
elif _database_engine == "sqlite":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": env_path("KYC_SQLITE_PATH", "var/shanakht.sqlite3")}}
else:
    raise ValueError("KYC_DATABASE_ENGINE must be sqlite or postgresql")
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("KYC_TIME_ZONE", "Asia/Karachi")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = env_path("KYC_STATIC_ROOT", "var/static")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django rejects an over-large request before DRF parses it; uploads are also
# checked independently using their actual byte count.
KYC_MAX_UPLOAD_BYTES = env_int("KYC_MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
KYC_MAX_REQUEST_BYTES = env_int("KYC_MAX_REQUEST_BYTES", 32 * 1024 * 1024)
DATA_UPLOAD_MAX_MEMORY_SIZE = KYC_MAX_REQUEST_BYTES
FILE_UPLOAD_MAX_MEMORY_SIZE = min(KYC_MAX_UPLOAD_BYTES, 2_621_440)
DATA_UPLOAD_MAX_NUMBER_FILES = env_int("KYC_MAX_UPLOAD_FILES", 4)
DATA_UPLOAD_MAX_NUMBER_FIELDS = env_int("KYC_MAX_FORM_FIELDS", 10)
FILE_UPLOAD_HANDLERS = [
    "detector.upload_handlers.TotalUploadLimitHandler",
    "django.core.files.uploadhandler.MemoryFileUploadHandler",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]
KYC_MAX_IMAGE_DIMENSION = env_int("KYC_MAX_IMAGE_DIMENSION", 10_000)
KYC_MAX_IMAGE_PIXELS = env_int("KYC_MAX_IMAGE_PIXELS", 40_000_000)
KYC_MIN_CARD_WIDTH = env_int("KYC_MIN_CARD_WIDTH", 640)
KYC_MIN_CARD_HEIGHT = env_int("KYC_MIN_CARD_HEIGHT", 400)

# There is deliberately no MEDIA_URL route. Request folders are private and
# get a random storage identifier independent of the public request ID.
KYC_PRIVATE_STORAGE_ROOT = env_path("KYC_PRIVATE_STORAGE_ROOT", "var/private-kyc")
KYC_PRESERVE_UPLOADS = env_bool("KYC_PRESERVE_UPLOADS", True)
KYC_RETENTION_HOURS = env_int("KYC_RETENTION_HOURS", 24)
KYC_OBJECT_STORAGE_BACKEND = os.getenv("KYC_OBJECT_STORAGE_BACKEND", "filesystem").strip().lower()
KYC_OBJECT_STORAGE_ROOT = env_path("KYC_OBJECT_STORAGE_ROOT", "var/private-objects")
KYC_S3_BUCKET = os.getenv("KYC_S3_BUCKET", "").strip()
KYC_S3_ENDPOINT_URL = os.getenv("KYC_S3_ENDPOINT_URL", "").strip() or None
KYC_S3_REGION = os.getenv("KYC_S3_REGION", "").strip() or None
KYC_S3_ACCESS_KEY_ID = os.getenv("KYC_S3_ACCESS_KEY_ID", "").strip() or None
KYC_S3_SECRET_ACCESS_KEY = os.getenv("KYC_S3_SECRET_ACCESS_KEY", "").strip() or None
KYC_S3_SERVER_SIDE_ENCRYPTION = os.getenv("KYC_S3_SERVER_SIDE_ENCRYPTION", "AES256").strip()

KYC_QUALITY_GATES_ENABLED = env_bool("KYC_QUALITY_GATES_ENABLED", True)
KYC_BLUR_THRESHOLD = env_float("KYC_BLUR_THRESHOLD", 80.0)
KYC_DARK_MEAN_THRESHOLD = env_float("KYC_DARK_MEAN_THRESHOLD", 45.0)
KYC_BRIGHT_MEAN_THRESHOLD = env_float("KYC_BRIGHT_MEAN_THRESHOLD", 225.0)
KYC_GLARE_RATIO_THRESHOLD = env_float("KYC_GLARE_RATIO_THRESHOLD", 0.08)
KYC_MIN_CARD_AREA_RATIO = env_float("KYC_MIN_CARD_AREA_RATIO", 0.12)

KYC_DEVICE = os.getenv("KYC_DEVICE", "cpu").strip().lower()
if KYC_DEVICE not in {"cpu", "cuda", "auto"}:
    raise ValueError("KYC_DEVICE must be one of: cpu, cuda, auto")

KYC_OCR_ENABLED = env_bool("KYC_OCR_ENABLED", True)
KYC_OCR_REQUIRED = env_bool("KYC_OCR_REQUIRED", True)
KYC_OCR_LANGUAGES = env_list("KYC_OCR_LANGUAGES", "en,ur")
KYC_OCR_ROTATION_INFO = tuple(
    value
    for value in (int(item) for item in env_list("KYC_OCR_ROTATION_INFO", "180"))
    if value in {90, 180, 270}
)
KYC_OCR_MODEL_DIR = env_path("KYC_OCR_MODEL_DIR", "var/models/easyocr")
KYC_OCR_DOWNLOAD_ENABLED = env_bool("KYC_OCR_DOWNLOAD_ENABLED", False)

_detector_path = os.getenv("KYC_CARD_DETECTOR_MODEL", "").strip()
KYC_CARD_DETECTOR_MODEL = None
if _detector_path:
    _candidate = Path(_detector_path).expanduser()
    KYC_CARD_DETECTOR_MODEL = _candidate if _candidate.is_absolute() else (REPOSITORY_ROOT / _candidate).resolve()
KYC_CARD_DETECTOR_SHA256 = os.getenv("KYC_CARD_DETECTOR_SHA256", "").strip().lower()
KYC_CARD_DETECTOR_REQUIRED = env_bool("KYC_CARD_DETECTOR_REQUIRED", False)
KYC_CARD_DETECTOR_CONFIDENCE = env_float("KYC_CARD_DETECTOR_CONFIDENCE", 0.20)
KYC_CARD_DETECTOR_IOU = env_float("KYC_CARD_DETECTOR_IOU", 0.30)

# Phase 2 detector registry. A configured detector may still report unavailable
# when its separately licensed/checksummed model is absent.
KYC_ENABLED_DETECTORS = env_list(
    "KYC_ENABLED_DETECTORS",
    "document_consistency,layout_landmarks,selfie_quality,face_comparison,liveness,tampering,duplicate",
)
KYC_REQUIRED_CHECKS = env_list("KYC_REQUIRED_CHECKS", "document_consistency,selfie_quality,face_comparison,liveness")
KYC_POLICY_VERSION = os.getenv("KYC_POLICY_VERSION", "phase2-policy-v1").strip()
KYC_FACE_DETECTOR_MODEL = env_path("KYC_FACE_DETECTOR_MODEL", "var/models/face/yunet.onnx")
KYC_FACE_DETECTOR_SHA256 = os.getenv("KYC_FACE_DETECTOR_SHA256", "").strip().lower()
KYC_FACE_RECOGNITION_MODEL = env_path("KYC_FACE_RECOGNITION_MODEL", "var/models/face/sface.onnx")
KYC_FACE_RECOGNITION_SHA256 = os.getenv("KYC_FACE_RECOGNITION_SHA256", "").strip().lower()
KYC_FACE_MATCH_THRESHOLD = env_float("KYC_FACE_MATCH_THRESHOLD", 0.363)
KYC_FACE_UNCERTAIN_MARGIN = env_float("KYC_FACE_UNCERTAIN_MARGIN", 0.04)
KYC_ANTI_SPOOF_MODEL = env_path("KYC_ANTI_SPOOF_MODEL", "var/models/liveness/anti-spoof.onnx")
KYC_ANTI_SPOOF_SHA256 = os.getenv("KYC_ANTI_SPOOF_SHA256", "").strip().lower()
KYC_LIVENESS_SESSION_SECONDS = env_int("KYC_LIVENESS_SESSION_SECONDS", 120)
KYC_LIVENESS_ACTIONS = env_list("KYC_LIVENESS_ACTIONS", "turn_left,turn_right,look_center")
KYC_IDENTIFIER_HMAC_KEY = os.getenv("KYC_IDENTIFIER_HMAC_KEY", "").strip()
KYC_WEBHOOK_ENCRYPTION_KEY = os.getenv("KYC_WEBHOOK_ENCRYPTION_KEY", "").strip()
KYC_WEBHOOK_TIMEOUT_SECONDS = env_int("KYC_WEBHOOK_TIMEOUT_SECONDS", 5)
KYC_WEBHOOK_ALLOW_HTTP = env_bool("KYC_WEBHOOK_ALLOW_HTTP", False)
KYC_CREATE_ACCOUNTS_ENABLED = env_bool("KYC_CREATE_ACCOUNTS_ENABLED", False)
KYC_MAX_BATCH_SIZE = env_int("KYC_MAX_BATCH_SIZE", 20)
KYC_FEATURE_PASSPORT_MRZ = env_bool("KYC_FEATURE_PASSPORT_MRZ", False)
KYC_FEATURE_PUNJAB_DRIVING_LICENSE = env_bool("KYC_FEATURE_PUNJAB_DRIVING_LICENSE", False)
KYC_AUTHORITATIVE_PROVIDER = os.getenv("KYC_AUTHORITATIVE_PROVIDER", "unavailable").strip()

# Celery uses eager execution for the documented single-process development
# profile. Production/staging set this false and provide Redis or RabbitMQ.
CELERY_BROKER_URL = os.getenv("KYC_CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("KYC_CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_TASK_ALWAYS_EAGER = env_bool("KYC_TASK_ALWAYS_EAGER", True)
CELERY_TASK_EAGER_PROPAGATES = env_bool("KYC_TASK_EAGER_PROPAGATES", False)
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_TIME_LIMIT = env_int("KYC_TASK_TIME_LIMIT_SECONDS", 300)
CELERY_TASK_SOFT_TIME_LIMIT = env_int("KYC_TASK_SOFT_TIME_LIMIT_SECONDS", 270)
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

KYC_API_KEYS = env_list("KYC_API_KEYS")
KYC_API_KEY_HEADER = os.getenv("KYC_API_KEY_HEADER", "X-API-Key").strip()
KYC_RATE_LIMIT = os.getenv("KYC_RATE_LIMIT", "30/minute").strip()

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["detector.authentication.APIKeyAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.MultiPartParser"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"kyc_processing": KYC_RATE_LIMIT, "anon": os.getenv("KYC_AUTH_RATE_LIMIT", "10/minute")},
    "EXCEPTION_HANDLER": "detector.errors.kyc_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Shanakht KYC API",
    "DESCRIPTION": "Tenant-scoped KYC orchestration. Local checks are not authoritative identity verification.",
    "VERSION": "2.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# Application code logs lifecycle metadata only. It must never log bodies, OCR
# text, CNIC values, images, or biometric information.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{levelname} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {
        "detector": {
            "handlers": ["console"],
            "level": os.getenv("KYC_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
