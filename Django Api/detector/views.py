from __future__ import annotations

from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .errors import KYCError
from .model_registry import get_model_registry
from .pipeline import process_pair
from .serialization import has_legacy_side_mismatch, legacy_response


class LivenessView(APIView):
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
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        result = get_model_registry().readiness(load_models=True)
        payload = {
            "request_id": request.request_id,
            "status": "ready" if result["ready"] else "not_ready",
            "ready": result["ready"],
            "checks": result["checks"],
        }
        response_status = status.HTTP_200_OK if result["ready"] else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=response_status)


class ProcessView(APIView):
    """Structured Phase 1 processing contract."""

    parser_classes = [MultiPartParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "kyc_processing"

    def post(self, request):
        front, back = _required_pair(request, "front", "back")
        template = request.data.get("template", "auto")
        return Response(process_pair(front, back, request.request_id, template=template), status=status.HTTP_200_OK)


class LegacyDetectorView(APIView):
    """Compatibility adapter for the original path, field names, and keys."""

    parser_classes = [MultiPartParser]
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
