from __future__ import annotations

from io import BytesIO
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import Resolver404, resolve
from PIL import Image
from rest_framework.test import APISimpleTestCase

from .views import LegacyDetectorView


PROCESS_URL = "/api/v1/kyc/process"
LEGACY_URL = "/api/v1/card/detector"
LIVE_URL = "/health/live"
READY_URL = "/health/ready"
API_KEY = "phase-one-test-key-0000000001"


def _image_bytes(image_format: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 20), (40, 100, 160)).save(output, format=image_format)
    return output.getvalue()


def _upload(
    content: bytes | None = None,
    *,
    name: str = "capture.png",
    content_type: str = "image/png",
) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name,
        _image_bytes() if content is None else content,
        content_type=content_type,
    )


def _field(raw_value, normalized_value=None):
    return {
        "raw_value": raw_value,
        "normalized_value": normalized_value if normalized_value is not None else raw_value,
        "supported": True,
    }


def _structured_result(request_id: str, *, mismatch: bool = False) -> dict:
    side_consistency = {
        "status": "fail" if mismatch else "pass",
        "code": "cnic_sides_mismatch" if mismatch else "cnic_sides_match",
        "message": "The CNIC values differ." if mismatch else "The CNIC values agree.",
    }
    return {
        "request_id": request_id,
        "api_version": "v1",
        "processing": {"success": True, "status": "completed", "duration_ms": 12.5},
        "verification": {
            "decision": "fail" if mismatch else "pass",
            "authoritative_issuance_checked": False,
            "message": "Local checks are not proof of issuance.",
        },
        "document": {
            "type": "pakistani_cnic",
            "layout": "generic",
            "layout_status": "uncertain",
            "detected_sides": {
                "front_upload": {"detected_side": "front", "status": "pass"},
                "back_upload": {"detected_side": "back", "status": "pass"},
            },
            "detections": {"front": [], "back": []},
        },
        "quality": {"overall_status": "pass", "front": [], "back": []},
        "extracted_fields": {
            "name": _field("Ali.Khan", "Ali.Khan"),
            "guardian_name": _field("Sara.Khan", "Sara.Khan"),
            "cnic_number": _field("12345-1234567-1", "12345-1234567-1"),
            "date_of_birth": _field("02.01.1990", "1990-01-02"),
            "date_of_issue": _field("04.03.2020", "2020-03-04"),
            "date_of_expiry": _field("04.03.2030", "2030-03-04"),
        },
        "field_evidence": {},
        "ocr": {
            "engine": "EasyOCR",
            "raw_detections": {"front": [], "back": []},
            "ordering": "top_to_bottom_with_per_line_unicode_direction",
        },
        "validation": {"overall_status": "fail" if mismatch else "pass", "checks": {"side_consistency": side_consistency}},
        "model_versions": {
            "card_boundary": {
                "name": "opencv-contour-baseline",
                "version": "test",
                "kind": "deterministic_heuristic",
            }
        },
    }


@override_settings(KYC_API_KEYS=[API_KEY])
class HealthAndAuthenticationTests(APISimpleTestCase):
    def test_liveness_is_public_and_echoes_safe_request_id(self):
        response = self.client.get(LIVE_URL, HTTP_X_REQUEST_ID="live-check-01")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Request-ID"], "live-check-01")
        self.assertEqual(
            response.json(),
            {
                "request_id": "live-check-01",
                "status": "ok",
                "service": "pakistani-cnic-kyc-api",
            },
        )

    def test_readiness_is_public_and_returns_503_when_models_are_not_ready(self):
        registry = Mock()
        registry.readiness.return_value = {
            "ready": False,
            "checks": [
                {"name": "ocr", "status": "fail", "reason": "weights_missing"},
                {"name": "card_detector", "status": "pass", "reason": "baseline"},
            ],
            "models": {"ocr": {"weights": [{"sha256": "private-fingerprint"}]}},
        }
        with patch("detector.views.get_model_registry", return_value=registry):
            response = self.client.get(READY_URL, HTTP_X_REQUEST_ID="ready-check-01")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["X-Request-ID"], "ready-check-01")
        self.assertEqual(response.json()["request_id"], "ready-check-01")
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertFalse(response.json()["ready"])
        self.assertNotIn("models", response.json())
        self.assertEqual(response["Cache-Control"], "no-store")
        registry.readiness.assert_called_once_with(load_models=True)

    def test_processing_requires_an_api_key(self):
        with patch("detector.views.process_pair") as process_pair:
            response = self.client.post(PROCESS_URL, {}, format="multipart")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")
        self.assertIsNotNone(response.json()["request_id"])
        self.assertEqual(response["X-Request-ID"], response.json()["request_id"])
        self.assertEqual(response["Cache-Control"], "no-store")
        process_pair.assert_not_called()

    def test_missing_sides_are_a_structured_400(self):
        response = self.client.post(
            PROCESS_URL,
            {},
            format="multipart",
            HTTP_X_API_KEY=API_KEY,
            HTTP_X_REQUEST_ID="missing-pair-01",
        )

        body = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response["X-Request-ID"], "missing-pair-01")
        self.assertEqual(body["request_id"], "missing-pair-01")
        self.assertEqual(body["error"]["code"], "missing_document_side")
        self.assertEqual(body["error"]["details"]["missing_fields"], ["front", "back"])

    def test_get_on_processing_endpoint_is_a_structured_405(self):
        response = self.client.get(
            PROCESS_URL,
            HTTP_X_API_KEY=API_KEY,
            HTTP_X_REQUEST_ID="wrong-method-01",
        )

        body = response.json()
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["X-Request-ID"], "wrong-method-01")
        self.assertEqual(body["request_id"], "wrong-method-01")
        self.assertEqual(body["error"]["code"], "method_not_allowed")
        self.assertIn("framework_detail", body["error"]["details"])

    def test_non_multipart_processing_request_is_a_structured_415(self):
        response = self.client.post(
            PROCESS_URL,
            {},
            format="json",
            HTTP_X_API_KEY=API_KEY,
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["error"]["code"], "unsupported_request_media_type")


@override_settings(KYC_API_KEYS=[API_KEY])
class UploadRoutingTests(APISimpleTestCase):
    def _post_pair(self, front: SimpleUploadedFile):
        return self.client.post(
            PROCESS_URL,
            {"front": front, "back": _upload(name="back.png")},
            format="multipart",
            HTTP_X_API_KEY=API_KEY,
        )

    def test_empty_upload_routes_to_structured_400(self):
        response = self._post_pair(_upload(b"", name="empty.png"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "empty_upload")

    def test_corrupt_upload_routes_to_structured_422(self):
        response = self._post_pair(_upload(b"not an image", name="broken.jpg", content_type="image/jpeg"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "image_decode_failed")
        self.assertEqual(response.json()["error"]["details"]["side"], "front")

    def test_unsupported_actual_image_format_routes_to_structured_415(self):
        response = self._post_pair(
            _upload(
                _image_bytes("GIF"),
                name="pretends-to-be.jpg",
                content_type="image/jpeg",
            )
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["error"]["code"], "unsupported_image_format")
        self.assertEqual(response.json()["error"]["details"]["detected_format"], "GIF")

    @override_settings(KYC_MAX_UPLOAD_BYTES=32)
    def test_oversized_upload_routes_to_structured_413(self):
        response = self._post_pair(_upload(b"x" * 33, name="too-large.png"))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "upload_too_large")
        self.assertEqual(response.json()["error"]["details"]["maximum_bytes"], 32)


@override_settings(KYC_API_KEYS=[API_KEY])
class CanonicalContractTests(APISimpleTestCase):
    def test_canonical_success_exposes_the_phase_one_schema(self):
        def fake_process(_front, _back, request_id, **_options):
            return _structured_result(request_id)

        with patch("detector.views.process_pair", side_effect=fake_process) as process_pair:
            response = self.client.post(
                PROCESS_URL,
                {"front": _upload(name="front.png"), "back": _upload(name="back.png")},
                format="multipart",
                HTTP_X_API_KEY=API_KEY,
                HTTP_X_REQUEST_ID="canonical-01",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Request-ID"], "canonical-01")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Pragma"], "no-cache")
        body = response.json()
        self.assertEqual(body["request_id"], "canonical-01")
        self.assertEqual(body["api_version"], "v1")
        self.assertEqual(
            set(body),
            {
                "request_id",
                "api_version",
                "processing",
                "verification",
                "document",
                "quality",
                "extracted_fields",
                "field_evidence",
                "ocr",
                "validation",
                "model_versions",
            },
        )
        self.assertTrue(body["processing"]["success"])
        self.assertFalse(body["verification"]["authoritative_issuance_checked"])
        self.assertEqual(body["document"]["type"], "pakistani_cnic")
        self.assertIn(body["quality"]["overall_status"], {"pass", "fail", "uncertain", "not_run", "unavailable"})
        process_pair.assert_called_once()
        self.assertEqual(process_pair.call_args.args[2], "canonical-01")
        self.assertEqual(process_pair.call_args.kwargs, {"template": "auto"})


@override_settings(KYC_API_KEYS=[API_KEY])
class LegacyCompatibilityTests(APISimpleTestCase):
    def test_exact_legacy_path_has_no_trailing_slash(self):
        match = resolve(LEGACY_URL)
        self.assertIs(match.func.view_class, LegacyDetectorView)
        self.assertEqual(match.url_name, "id_detector")
        with self.assertRaises(Resolver404):
            resolve(f"{LEGACY_URL}/")

    def test_legacy_route_requires_the_historical_multipart_names(self):
        response = self.client.post(
            LEGACY_URL,
            {"front": _upload(name="front.png"), "back": _upload(name="back.png")},
            format="multipart",
            HTTP_X_API_KEY=API_KEY,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"]["details"]["missing_fields"],
            ["front_imagee", "back_image"],
        )

    def test_legacy_success_maps_to_the_exact_six_key_contract(self):
        def fake_process(_front, _back, request_id):
            return _structured_result(request_id)

        with patch("detector.views.process_pair", side_effect=fake_process):
            response = self.client.post(
                LEGACY_URL,
                {
                    "front_imagee": _upload(name="front.png"),
                    "back_image": _upload(name="back.png"),
                },
                format="multipart",
                HTTP_X_API_KEY=API_KEY,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "Name": "AliKhan",
                "Gaurdian Name": "SaraKhan",
                "Id Card Number": "1234512345671",
                "Data Of Birth": "020190",
                "Data Of Issue": "040320",
                "Data Of Expiry": "040330",
            },
        )

    def test_legacy_side_mismatch_retains_exact_406_body(self):
        def fake_process(_front, _back, request_id):
            return _structured_result(request_id, mismatch=True)

        with patch("detector.views.process_pair", side_effect=fake_process):
            response = self.client.post(
                LEGACY_URL,
                {
                    "front_imagee": _upload(name="front.png"),
                    "back_image": _upload(name="back.png"),
                },
                format="multipart",
                HTTP_X_API_KEY=API_KEY,
            )

        self.assertEqual(response.status_code, 406)
        self.assertEqual(
            response.json(),
            {"error": "FRONT SIDE & BACK SIDE OF THE CARD ARE NOT SAME"},
        )


class CNICAutoDetectEndpointTests(APISimpleTestCase):
    def test_missing_upload_returns_400(self):
        response = self.client.post("/api/v2/cnic/detect", {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "missing_upload")

    def test_successful_detect_returns_201_with_application(self):
        fake_result = {
            "application_id": "00000000-0000-0000-0000-000000000001",
            "display_id": "APP-00000000",
            "artifact_id": "1",
            "detected_side": "front",
            "extracted_fields": {
                "name": {"raw_value": "Ali", "normalized_value": "Ali", "source": "machine"},
                "cnic_number": {"raw_value": "35201-1234567-1", "normalized_value": "35201-1234567-1", "source": "machine"},
            },
            "raw_ocr_count": 5,
        }
        with patch("detector.extraction_service.detect_and_store_single_image", return_value=fake_result):
            response = self.client.post(
                "/api/v2/cnic/detect",
                {"file": _upload(name="card.png")},
                format="multipart",
            )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["display_id"], "APP-00000000")
        self.assertIn("cnic_number", data["extracted_fields"])
