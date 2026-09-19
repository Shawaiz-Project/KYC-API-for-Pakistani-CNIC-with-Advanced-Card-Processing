from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import ModuleType, SimpleNamespace
import uuid
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from detector.authentication import APIKeyAuthentication
from detector.middleware import RequestIDMiddleware
from detector.model_registry import ModelRegistry, ModelUnavailableError, sha256_file
from detector.upload_handlers import TotalUploadLimitHandler


VALID_API_KEY = "operator-secret-key-0000000001"


class RequestIDMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_accepts_safe_caller_request_id_and_echoes_it(self):
        request = self.factory.get("/health", HTTP_X_REQUEST_ID="client.abc:123_test-value")
        seen = {}

        def endpoint(current_request):
            seen["request_id"] = current_request.request_id
            return HttpResponse(status=204)

        response = RequestIDMiddleware(endpoint)(request)

        self.assertEqual(seen["request_id"], "client.abc:123_test-value")
        self.assertEqual(response["X-Request-ID"], "client.abc:123_test-value")

    def test_replaces_invalid_request_id_with_uuid(self):
        request = self.factory.get("/health", HTTP_X_REQUEST_ID="unsafe value\r\nX-Leak: yes")
        response = RequestIDMiddleware(lambda _: HttpResponse(status=204))(request)

        generated = uuid.UUID(response["X-Request-ID"])
        self.assertEqual(str(generated), request.request_id)
        self.assertNotIn("unsafe", response["X-Request-ID"])
        self.assertNotIn("\r", response["X-Request-ID"])
        self.assertNotIn("\n", response["X-Request-ID"])

    def test_replaces_cnic_shaped_request_id_so_it_cannot_reach_logs(self):
        supplied = "12345-1234567-1"
        request = self.factory.get("/health", HTTP_X_REQUEST_ID=supplied)
        response = RequestIDMiddleware(lambda _: HttpResponse(status=204))(request)

        uuid.UUID(response["X-Request-ID"])
        self.assertNotEqual(response["X-Request-ID"], supplied)
        self.assertNotEqual(request.request_id, supplied)


class APIKeyAuthenticationTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.authenticator = APIKeyAuthentication()

    @override_settings(KYC_API_KEYS=(VALID_API_KEY,), KYC_API_KEY_HEADER="X-API-Key")
    def test_configured_key_returns_only_a_non_reversible_principal(self):
        request = self.factory.get("/", HTTP_X_API_KEY=VALID_API_KEY)

        principal, auth = self.authenticator.authenticate(request)

        self.assertIsNone(auth)
        self.assertTrue(principal.is_authenticated)
        self.assertEqual(principal.username, "api-key")
        self.assertEqual(principal.pk, hashlib.sha256(VALID_API_KEY.encode()).hexdigest())
        self.assertNotIn(VALID_API_KEY, repr(principal))

    @override_settings(KYC_API_KEYS=(VALID_API_KEY,), KYC_API_KEY_HEADER="X-API-Key")
    def test_missing_header_defers_to_permission_handling(self):
        request = self.factory.get("/")
        self.assertIsNone(self.authenticator.authenticate(request))

    @override_settings(KYC_API_KEYS=(), KYC_API_KEY_HEADER="X-API-Key")
    def test_missing_configuration_fails_closed_without_leaking_provided_key(self):
        supplied = "do-not-echo-this-key"
        request = self.factory.get("/", HTTP_X_API_KEY=supplied)

        with self.assertRaises(AuthenticationFailed) as raised:
            self.authenticator.authenticate(request)

        rendered = f"{raised.exception!s} {raised.exception!r} {raised.exception.detail!r}"
        self.assertNotIn(supplied, rendered)
        self.assertIn("authentication_unavailable", rendered)

    @override_settings(KYC_API_KEYS=(VALID_API_KEY,), KYC_API_KEY_HEADER="X-API-Key")
    def test_invalid_key_fails_without_leaking_supplied_or_configured_key(self):
        supplied = "incorrect-secret"
        request = self.factory.get("/", HTTP_X_API_KEY=supplied)

        with self.assertRaises(AuthenticationFailed) as raised:
            self.authenticator.authenticate(request)

        rendered = f"{raised.exception!s} {raised.exception!r} {raised.exception.detail!r}"
        self.assertNotIn(supplied, rendered)
        self.assertNotIn(VALID_API_KEY, rendered)
        self.assertIn("invalid_api_key", rendered)

    @override_settings(
        KYC_API_KEYS=("replace-with-a-random-api-key",),
        KYC_API_KEY_HEADER="X-API-Key",
    )
    def test_example_placeholder_key_is_never_accepted(self):
        request = self.factory.get(
            "/", HTTP_X_API_KEY="replace-with-a-random-api-key"
        )

        with self.assertRaises(AuthenticationFailed) as raised:
            self.authenticator.authenticate(request)

        self.assertIn("authentication_unavailable", str(raised.exception.detail))


class StreamingUploadLimitTests(SimpleTestCase):
    @override_settings(KYC_MAX_REQUEST_BYTES=5)
    def test_aggregate_file_chunks_are_capped_without_content_length(self):
        handler = TotalUploadLimitHandler()
        self.assertEqual(handler.receive_data_chunk(b"123", 0), b"123")
        with self.assertRaises(RequestDataTooBig):
            handler.receive_data_chunk(b"456", 3)


class ModelRegistryTests(SimpleTestCase):
    @override_settings(
        KYC_OCR_REQUIRED=False,
        KYC_OCR_ROTATION_INFO=(180,),
    )
    def test_optional_unavailable_ocr_degrades_to_empty_results(self):
        registry = ModelRegistry()
        registry._ocr_error = ModelUnavailableError("OCR", "weights_missing_or_invalid")

        self.assertEqual(registry.run_ocr(object()), [])

    @override_settings(KYC_OCR_ROTATION_INFO=(180,))
    def test_ocr_checks_upside_down_text_without_reloading_reader(self):
        registry = ModelRegistry()
        reader = Mock()
        reader.readtext.return_value = []
        registry._ocr_reader = reader
        image = object()

        registry.run_ocr(image)

        reader.readtext.assert_called_once_with(
            image,
            detail=1,
            paragraph=False,
            rotation_info=[180],
        )

    @override_settings(
        SECRET_KEY="replace-with-a-long-random-value",
        KYC_API_KEYS=("replace-with-a-random-api-key",),
        KYC_OCR_ENABLED=False,
        KYC_OCR_REQUIRED=False,
    )
    def test_readiness_rejects_example_credentials(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(
            KYC_PRIVATE_STORAGE_ROOT=Path(directory) / "private"
        ):
            result = ModelRegistry().readiness(load_models=False)

        checks = {item["name"]: item for item in result["checks"]}
        self.assertEqual(checks["secret_key"]["status"], "fail")
        self.assertEqual(checks["api_authentication"]["status"], "fail")
        self.assertFalse(result["ready"])

    @override_settings(KYC_DEVICE="cpu")
    def test_cpu_device_forces_cpu_onnx_provider(self):
        fake_onnxruntime = SimpleNamespace(
            get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"]
        )
        with patch.dict(sys.modules, {"onnxruntime": fake_onnxruntime}):
            providers = ModelRegistry()._onnx_providers()
        self.assertEqual(providers, ["CPUExecutionProvider"])

    @override_settings(KYC_DEVICE="cuda")
    def test_strict_cuda_rejects_missing_cuda_provider(self):
        fake_onnxruntime = SimpleNamespace(get_available_providers=lambda: ["CPUExecutionProvider"])
        with patch.dict(sys.modules, {"onnxruntime": fake_onnxruntime}):
            with self.assertRaises(ModelUnavailableError) as raised:
                ModelRegistry()._onnx_providers()
        self.assertEqual(raised.exception.details["component"], "card detector")
        self.assertEqual(raised.exception.details["reason"], "cuda_provider_not_available")

    def test_checksum_mismatch_is_an_explicit_model_error(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "detector.onnx"
            model_path.write_bytes(b"not-a-real-model")
            with override_settings(
                KYC_CARD_DETECTOR_MODEL=model_path,
                KYC_CARD_DETECTOR_SHA256="0" * 64,
                KYC_CARD_DETECTOR_REQUIRED=True,
            ):
                with self.assertRaises(ModelUnavailableError) as raised:
                    ModelRegistry().get_card_detector()

        self.assertEqual(raised.exception.details["component"], "card detector")
        self.assertEqual(raised.exception.details["reason"], "sha256_mismatch")

    def test_detector_is_loaded_once_when_called_concurrently(self):
        constructor_calls = []
        constructor_lock = threading.Lock()
        fake_yolov8 = ModuleType("yolov8")

        class FakeYOLOv8:
            def __init__(self, path, *, conf_thres, iou_thres, providers):
                with constructor_lock:
                    constructor_calls.append(
                        {
                            "path": path,
                            "conf_thres": conf_thres,
                            "iou_thres": iou_thres,
                            "providers": providers,
                        }
                    )
                # Make lock races observable without making the test slow.
                time.sleep(0.02)

            def __call__(self, image):
                return [], [], []

        fake_yolov8.YOLOv8 = FakeYOLOv8

        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "detector.onnx"
            model_path.write_bytes(b"model-fixture")
            checksum = sha256_file(model_path)
            registry = ModelRegistry()
            original_sys_path = list(sys.path)
            try:
                with override_settings(
                    KYC_CARD_DETECTOR_MODEL=model_path,
                    KYC_CARD_DETECTOR_SHA256=checksum,
                    KYC_CARD_DETECTOR_REQUIRED=True,
                    KYC_CARD_DETECTOR_CONFIDENCE=0.25,
                    KYC_CARD_DETECTOR_IOU=0.35,
                    REPOSITORY_ROOT=Path(directory),
                ), patch.object(
                    registry, "_onnx_providers", return_value=["CPUExecutionProvider"]
                ), patch.dict(sys.modules, {"yolov8": fake_yolov8}):
                    with ThreadPoolExecutor(max_workers=12) as executor:
                        detectors = list(executor.map(lambda _: registry.get_card_detector(), range(24)))
            finally:
                sys.path[:] = original_sys_path

        self.assertEqual(len(constructor_calls), 1)
        self.assertTrue(all(detector is detectors[0] for detector in detectors))
        self.assertEqual(constructor_calls[0]["providers"], ["CPUExecutionProvider"])
        self.assertEqual(detectors[0].version["sha256"], checksum)


class ModelManifestCommandTests(SimpleTestCase):
    def test_empty_model_assets_emit_an_empty_privacy_safe_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory) / "easyocr-does-not-exist"
            output = StringIO()
            with override_settings(
                KYC_OCR_MODEL_DIR=model_dir,
                KYC_OCR_LANGUAGES=("en", "ur"),
                KYC_CARD_DETECTOR_MODEL=None,
            ):
                call_command("model_manifest", stdout=output)

            payload = json.loads(output.getvalue())

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["easyocr"], {"languages": ["en", "ur"], "files": []})
        self.assertIsNone(payload["card_detector"])
        self.assertNotIn(directory, output.getvalue())
