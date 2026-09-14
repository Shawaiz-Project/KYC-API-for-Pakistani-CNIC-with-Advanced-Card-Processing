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
    "detector",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
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
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django rejects an over-large request before DRF parses it; uploads are also
# checked independently using their actual byte count.
KYC_MAX_UPLOAD_BYTES = env_int("KYC_MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
KYC_MAX_REQUEST_BYTES = env_int("KYC_MAX_REQUEST_BYTES", 21 * 1024 * 1024)
DATA_UPLOAD_MAX_MEMORY_SIZE = KYC_MAX_REQUEST_BYTES
FILE_UPLOAD_MAX_MEMORY_SIZE = min(KYC_MAX_UPLOAD_BYTES, 2_621_440)
DATA_UPLOAD_MAX_NUMBER_FILES = env_int("KYC_MAX_UPLOAD_FILES", 2)
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

KYC_API_KEYS = env_list("KYC_API_KEYS")
KYC_API_KEY_HEADER = os.getenv("KYC_API_KEY_HEADER", "X-API-Key").strip()
KYC_RATE_LIMIT = os.getenv("KYC_RATE_LIMIT", "30/minute").strip()

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["detector.authentication.APIKeyAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.MultiPartParser"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"kyc_processing": KYC_RATE_LIMIT},
    "EXCEPTION_HANDLER": "detector.errors.kyc_exception_handler",
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
