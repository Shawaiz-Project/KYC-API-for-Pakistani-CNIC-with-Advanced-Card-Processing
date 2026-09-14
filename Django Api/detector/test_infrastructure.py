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
from unittest.mock import patch

from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from detector.authentication import APIKeyAuthentication
from detector.middleware import RequestIDMiddleware
from detector.model_registry import ModelRegistry, ModelUnavailableError, sha256_file


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


class APIKeyAuthenticationTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.authenticator = APIKeyAuthentication()

    @override_settings(KYC_API_KEYS=("operator-secret",), KYC_API_KEY_HEADER="X-API-Key")
    def test_configured_key_returns_only_a_non_reversible_principal(self):
        request = self.factory.get("/", HTTP_X_API_KEY="operator-secret")

        principal, auth = self.authenticator.authenticate(request)

        self.assertIsNone(auth)
        self.assertTrue(principal.is_authenticated)
        self.assertEqual(principal.username, "api-key")
        self.assertEqual(principal.pk, hashlib.sha256(b"operator-secret").hexdigest())
        self.assertNotIn("operator-secret", repr(principal))

    @override_settings(KYC_API_KEYS=("operator-secret",), KYC_API_KEY_HEADER="X-API-Key")
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

    @override_settings(KYC_API_KEYS=("configured-secret",), KYC_API_KEY_HEADER="X-API-Key")
    def test_invalid_key_fails_without_leaking_supplied_or_configured_key(self):
        supplied = "incorrect-secret"
        request = self.factory.get("/", HTTP_X_API_KEY=supplied)

        with self.assertRaises(AuthenticationFailed) as raised:
            self.authenticator.authenticate(request)

        rendered = f"{raised.exception!s} {raised.exception!r} {raised.exception.detail!r}"
        self.assertNotIn(supplied, rendered)
        self.assertNotIn("configured-secret", rendered)
        self.assertIn("invalid_api_key", rendered)


class ModelRegistryTests(SimpleTestCase):
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
