from __future__ import annotations

from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from django.conf import settings
from django.db import connection
from pathlib import Path

from .errors import KYCError
from .model_registry import get_model_registry
from .openapi import EmptySerializer
from .pipeline import process_pair
from .serialization import has_legacy_side_mismatch, legacy_response
from .checks.face import _verified_model
from .object_storage import get_object_store


class LivenessView(APIView):
    serializer_class = EmptySerializer
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        return Response(
            {
                "request_id": request.request_id,
                "status": "ok",
                "service": "pakistani-cnic-kyc-api",
            }
        )


class ReadinessView(APIView):
    serializer_class = EmptySerializer
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        result = get_model_registry().readiness(load_models=True)
        platform_checks = _phase3_readiness_checks(run_connections=bool(result["ready"]))
        ready = bool(result["ready"]) and all(item["status"] == "pass" for item in platform_checks)
        payload = {
            "request_id": request.request_id,
            "status": "ready" if ready else "not_ready",
            "ready": ready,
            "checks": [*result["checks"], *platform_checks],
        }
        response_status = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=response_status)


def _phase3_readiness_checks(*, run_connections: bool) -> list[dict[str, str]]:
    checks = []
    required = set(settings.KYC_REQUIRED_CHECKS)
    detector_ok = _verified_model(Path(settings.KYC_FACE_DETECTOR_MODEL), settings.KYC_FACE_DETECTOR_SHA256)
    recognizer_ok = _verified_model(Path(settings.KYC_FACE_RECOGNITION_MODEL), settings.KYC_FACE_RECOGNITION_SHA256)
    if "face_comparison" in required:
        checks.append({"name": "face_comparison", "status": "pass" if detector_ok and recognizer_ok else "fail", "reason": "verified_models" if detector_ok and recognizer_ok else "weights_missing_or_checksum_mismatch"})
    if "liveness" in required:
        checks.append({"name": "liveness_anti_spoof", "status": "fail", "reason": "evaluated_anti_spoof_adapter_unavailable"})
    if not run_connections:
        return checks
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks.append({"name": "database", "status": "pass", "reason": "connection_ok"})
    except Exception as exc:
        checks.append({"name": "database", "status": "fail", "reason": f"connection_failed:{type(exc).__name__}"})
    try:
        get_object_store()
        checks.append({"name": "private_object_storage", "status": "pass", "reason": "configured"})
    except Exception as exc:
        checks.append({"name": "private_object_storage", "status": "fail", "reason": f"configuration_failed:{type(exc).__name__}"})
    if settings.CELERY_TASK_ALWAYS_EAGER:
        checks.append({"name": "task_queue", "status": "pass", "reason": "eager_local_profile"})
    else:
        try:
            from api.celery import app
            with app.connection_for_read() as broker:
                broker.ensure_connection(max_retries=0, timeout=1)
            checks.append({"name": "task_queue", "status": "pass", "reason": "broker_connection_ok"})
        except Exception as exc:
            checks.append({"name": "task_queue", "status": "fail", "reason": f"broker_connection_failed:{type(exc).__name__}"})
    return checks


class ProcessView(APIView):
    """Structured Phase 1 processing contract."""

    parser_classes = [MultiPartParser]
    serializer_class = EmptySerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "kyc_processing"

    def post(self, request):
        front, back = _required_pair(request, "front", "back")
        template = request.data.get("template", "auto")
        return Response(process_pair(front, back, request.request_id, template=template), status=status.HTTP_200_OK)


class LegacyDetectorView(APIView):
    """Compatibility adapter for the original path, field names, and keys."""

    parser_classes = [MultiPartParser]
    serializer_class = EmptySerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "kyc_processing"

    def post(self, request):
        front, back = _required_pair(request, "front_imagee", "back_image")
        result = process_pair(front, back, request.request_id)
        if has_legacy_side_mismatch(result):
            return Response(
                {"error": "FRONT SIDE & BACK SIDE OF THE CARD ARE NOT SAME"},
                status=status.HTTP_406_NOT_ACCEPTABLE,
            )
        return Response(legacy_response(result), status=status.HTTP_200_OK)


def _required_pair(request, front_name: str, back_name: str):
    front = request.FILES.get(front_name)
    back = request.FILES.get(back_name)
    missing = []
    if front is None:
        missing.append(front_name)
    if back is None:
        missing.append(back_name)
    if missing:
        raise KYCError(
            "missing_document_side",
            "Both front and back document images are required.",
            status.HTTP_400_BAD_REQUEST,
            {"missing_fields": missing},
        )
    return front, back
