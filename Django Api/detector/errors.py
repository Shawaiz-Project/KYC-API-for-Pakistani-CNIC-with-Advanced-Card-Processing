from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from django.core.exceptions import RequestDataTooBig
from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    MethodNotAllowed,
    NotAuthenticated,
    ParseError,
    PermissionDenied,
    Throttled,
    UnsupportedMediaType,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


logger = logging.getLogger("detector.errors")


@dataclass
class KYCError(Exception):
    code: str
    message: str
    http_status: int = status.HTTP_400_BAD_REQUEST
    details: Any = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def error_response(request, error: KYCError) -> Response:
    payload = {
        "request_id": getattr(request, "request_id", None),
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details or {},
        },
    }
    return Response(payload, status=error.http_status)


def _drf_error(exc, response) -> KYCError:
    mapping = (
        (AuthenticationFailed, "invalid_authentication", "Authentication failed."),
        (NotAuthenticated, "authentication_required", "Authentication is required."),
        (PermissionDenied, "permission_denied", "Permission denied."),
        (Throttled, "rate_limited", "The request rate limit was exceeded."),
        (MethodNotAllowed, "method_not_allowed", "The HTTP method is not allowed."),
        (UnsupportedMediaType, "unsupported_request_media_type", "Use multipart/form-data."),
        (ParseError, "invalid_request", "The request body could not be parsed."),
    )
    code, message = "request_error", "The request could not be processed."
    for cls, candidate_code, candidate_message in mapping:
        if isinstance(exc, cls):
            code, message = candidate_code, candidate_message
            break

    data = response.data
    if isinstance(data, dict):
        detail = data.get("detail", data)
        if isinstance(detail, dict):
            code = str(detail.get("code", code))
            message = str(detail.get("message", message))
    return KYCError(code, message, response.status_code, {"framework_detail": data})


def kyc_exception_handler(exc, context):
    request = context.get("request")
    if isinstance(exc, KYCError):
        return error_response(request, exc)
    if isinstance(exc, RequestDataTooBig):
        return error_response(
            request,
            KYCError(
                "request_too_large",
                "The multipart request exceeds the configured upload limit.",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            ),
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.error(
            "Unhandled API exception request_id=%s exception_type=%s",
            getattr(request, "request_id", None),
            type(exc).__name__,
        )
        return error_response(
            request,
            KYCError(
                "internal_error",
                "The request could not be completed because of an internal error.",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
        )
    structured = error_response(request, _drf_error(exc, response))
    if "Retry-After" in response:
        structured["Retry-After"] = response["Retry-After"]
    return structured
