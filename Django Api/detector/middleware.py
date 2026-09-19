from __future__ import annotations

import re
import uuid

from django.conf import settings
from django.http import JsonResponse


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_CNIC_REQUEST_ID_RE = re.compile(r"^[0-9]{5}-?[0-9]{7}-?[0-9]$")


def _safe_request_id(value: str) -> bool:
    return bool(_REQUEST_ID_RE.fullmatch(value)) and not bool(
        _CNIC_REQUEST_ID_RE.fullmatch(value)
    )


class RequestIDMiddleware:
    """Attach a safe correlation ID without using request content or filenames."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.headers.get("X-Request-ID", "")
        request.request_id = supplied if _safe_request_id(supplied) else str(uuid.uuid4())
        content_length = request.META.get("CONTENT_LENGTH", "")
        try:
            request_bytes = int(content_length) if content_length else None
        except (TypeError, ValueError):
            request_bytes = None
        if request_bytes is not None and request_bytes > int(settings.KYC_MAX_REQUEST_BYTES):
            response = JsonResponse(
                {
                    "request_id": request.request_id,
                    "error": {
                        "code": "request_too_large",
                        "message": "The multipart request exceeds the configured upload limit.",
                        "details": {"maximum_bytes": int(settings.KYC_MAX_REQUEST_BYTES)},
                    },
                },
                status=413,
            )
            response["X-Request-ID"] = request.request_id
            response["Cache-Control"] = "no-store"
            response["Pragma"] = "no-cache"
            return response
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        if request.path.startswith("/api/") or request.path == "/health/ready":
            response["Cache-Control"] = "no-store"
            response["Pragma"] = "no-cache"
        return response
