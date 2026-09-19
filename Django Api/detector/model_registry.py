from __future__ import annotations

import hashlib
import importlib.metadata
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from django.conf import settings
from rest_framework import status

from .authentication import configured_api_keys
from .errors import KYCError
from .storage import UnsafeStoragePathError, validate_storage_root


class ModelUnavailableError(KYCError):
    def __init__(self, component: str, reason: str, *, details: dict[str, Any] | None = None):
        safe_details = {"component": component, "reason": reason}
        if details:
            safe_details.update(details)
        super().__init__(
            "model_unavailable",
            f"The required {component} model is unavailable.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            safe_details,
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def weight_manifest(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    records = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        records.append(
            {
                "file": path.relative_to(directory).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


class ThreadSafeYOLODetector:
    """Serializes access to the legacy mutable YOLO wrapper."""

    def __init__(self, model, version: dict[str, Any]):
        self._model = model
        self._lock = threading.Lock()
        self.version = version

    def detect(self, image) -> list[dict[str, Any]]:
        with self._lock:
            boxes, scores, class_ids = self._model(image)
            return [
                {
                    "bbox": [float(value) for value in box],
                    "score": float(score),
                    "class_id": int(class_id),
                }
                for box, score, class_id in zip(boxes, scores, class_ids)
            ]


class ModelRegistry:
    """Lazy, process-local registry; successful models are loaded once per worker."""

    def __init__(self):
        self._ocr_reader = None
        self._ocr_error: ModelUnavailableError | None = None
        self._ocr_lock = threading.RLock()
        self._ocr_inference_lock = threading.Lock()
        self._detector = None
        self._detector_loaded = False
        self._detector_error: ModelUnavailableError | None = None
        self._detector_lock = threading.RLock()
        self._model_versions: dict[str, dict[str, Any]] = {
            "card_boundary": {
                "name": "opencv-contour-baseline",
                "version": _package_version("opencv-python-headless", fallback="unknown"),
                "kind": "deterministic_heuristic",
            },
            "ocr": {
                "name": "EasyOCR",
                "version": _package_version("easyocr", fallback="unavailable"),
                "languages": list(settings.KYC_OCR_LANGUAGES),
                "rotation_candidates_degrees": list(settings.KYC_OCR_ROTATION_INFO),
                "device": settings.KYC_DEVICE,
                "status": "not_loaded" if settings.KYC_OCR_ENABLED else "disabled",
                "confidence": "raw_model_score_not_calibrated_probability",
            },
        }

    def _gpu_requested(self) -> bool:
        if settings.KYC_DEVICE == "cpu":
            return False
        try:
            import torch
        except ImportError as exc:
            if settings.KYC_DEVICE == "cuda":
                raise ModelUnavailableError("GPU runtime", "torch_not_installed") from exc
            return False
        available = bool(torch.cuda.is_available())
        if settings.KYC_DEVICE == "cuda" and not available:
            raise ModelUnavailableError("GPU runtime", "cuda_not_available")
        return available

    def get_ocr_reader(self, *, allow_download: bool | None = None):
        if not settings.KYC_OCR_ENABLED:
            if settings.KYC_OCR_REQUIRED:
                raise ModelUnavailableError("OCR", "disabled_but_required")
            return None
        if self._ocr_reader is not None:
            return self._ocr_reader
        if self._ocr_error is not None:
            raise self._ocr_error

        with self._ocr_lock:
            if self._ocr_reader is not None:
                return self._ocr_reader
            if self._ocr_error is not None:
                raise self._ocr_error
            try:
                import easyocr

                model_dir = Path(settings.KYC_OCR_MODEL_DIR)
                model_dir.mkdir(parents=True, exist_ok=True)
                download_enabled = settings.KYC_OCR_DOWNLOAD_ENABLED if allow_download is None else allow_download
                self._ocr_reader = easyocr.Reader(
                    list(settings.KYC_OCR_LANGUAGES),
                    gpu=self._gpu_requested(),
                    model_storage_directory=str(model_dir),
                    download_enabled=download_enabled,
                    verbose=False,
                )
                self._model_versions["ocr"] = {
                    "name": "EasyOCR",
                    "version": _package_version("easyocr", fallback=getattr(easyocr, "__version__", "unknown")),
                    "languages": list(settings.KYC_OCR_LANGUAGES),
                    "rotation_candidates_degrees": list(settings.KYC_OCR_ROTATION_INFO),
                    "device": str(getattr(self._ocr_reader, "device", settings.KYC_DEVICE)),
                    "weights": weight_manifest(model_dir),
                    "confidence": "raw_model_score_not_calibrated_probability",
                }
                return self._ocr_reader
            except ModelUnavailableError as exc:
                self._ocr_error = exc
                self._record_ocr_unavailable(exc)
                raise
            except ImportError as exc:
                self._ocr_error = ModelUnavailableError("OCR", "easyocr_not_installed")
                self._record_ocr_unavailable(self._ocr_error)
                raise self._ocr_error from exc
            except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
                self._ocr_error = ModelUnavailableError(
                    "OCR",
                    "weights_missing_or_invalid",
                    details={"exception_type": type(exc).__name__},
                )
                self._record_ocr_unavailable(self._ocr_error)
                raise self._ocr_error from exc

    def _record_ocr_unavailable(self, error: ModelUnavailableError) -> None:
        self._model_versions["ocr"] = {
            "name": "EasyOCR",
            "version": _package_version("easyocr", fallback="unavailable"),
            "languages": list(settings.KYC_OCR_LANGUAGES),
            "rotation_candidates_degrees": list(settings.KYC_OCR_ROTATION_INFO),
            "device": settings.KYC_DEVICE,
            "status": "unavailable",
            "reason": error.details["reason"],
            "confidence": "raw_model_score_not_calibrated_probability",
        }

    def run_ocr(self, image):
        try:
            reader = self.get_ocr_reader()
        except ModelUnavailableError:
            if settings.KYC_OCR_REQUIRED:
                raise
            return []
        if reader is None:
            return []
        # EasyOCR/PyTorch readers are shared per worker. Guard calls because not
        # every backend guarantees thread-safe access to the same module state.
        with self._ocr_inference_lock:
            return reader.readtext(
                image,
                detail=1,
                paragraph=False,
                rotation_info=list(settings.KYC_OCR_ROTATION_INFO) or None,
            )

    def get_card_detector(self):
        if self._detector_loaded:
            if self._detector_error and settings.KYC_CARD_DETECTOR_REQUIRED:
                raise self._detector_error
            return self._detector
        with self._detector_lock:
            if self._detector_loaded:
                if self._detector_error and settings.KYC_CARD_DETECTOR_REQUIRED:
                    raise self._detector_error
                return self._detector
            path = settings.KYC_CARD_DETECTOR_MODEL
            if path is None:
                self._detector_loaded = True
                if settings.KYC_CARD_DETECTOR_REQUIRED:
                    self._detector_error = ModelUnavailableError("card detector", "path_not_configured")
                    raise self._detector_error
                return None
            path = Path(path)
            try:
                if not path.is_file():
                    raise ModelUnavailableError("card detector", "weight_file_not_found")
                expected = settings.KYC_CARD_DETECTOR_SHA256
                actual = sha256_file(path)
                if not expected:
                    # SHA256 not configured — allowed when REQUIRED=false (dev/test).
                    # In production set KYC_CARD_DETECTOR_SHA256 and REQUIRED=true.
                    if settings.KYC_CARD_DETECTOR_REQUIRED:
                        raise ModelUnavailableError("card detector", "sha256_not_configured")
                    import logging as _logging
                    _logging.getLogger("detector.model_registry").warning(
                        "YOLO card detector loaded without SHA256 verification. "
                        "Set KYC_CARD_DETECTOR_SHA256=%s in .env for production.",
                        actual,
                    )
                elif actual != expected:
                    raise ModelUnavailableError("card detector", "sha256_mismatch")

                providers = self._onnx_providers()
                root = str(settings.REPOSITORY_ROOT)
                if root not in sys.path:
                    sys.path.insert(0, root)
                from yolov8 import YOLOv8

                model = YOLOv8(
                    str(path),
                    conf_thres=settings.KYC_CARD_DETECTOR_CONFIDENCE,
                    iou_thres=settings.KYC_CARD_DETECTOR_IOU,
                    providers=providers,
                )
                version = {
                    "name": "custom-yolov8-onnx-card-detector",
                    "version": actual[:12],
                    "sha256": actual,
                    "providers": providers,
                    "confidence": "raw_model_score_not_calibrated_probability",
                }
                self._detector = ThreadSafeYOLODetector(model, version)
                self._model_versions["card_detector"] = version
                self._detector_loaded = True
                return self._detector
            except ModelUnavailableError as exc:
                self._detector_error = exc
            except ImportError as exc:
                self._detector_error = ModelUnavailableError("card detector", "onnx_runtime_not_installed")
                self._detector_error.__cause__ = exc
            except (RuntimeError, ValueError, OSError) as exc:
                self._detector_error = ModelUnavailableError(
                    "card detector", "weight_load_failed", details={"exception_type": type(exc).__name__}
                )

            self._detector_loaded = True
            self._model_versions["card_detector"] = {
                "name": "custom-yolov8-onnx-card-detector",
                "status": "unavailable",
                "reason": self._detector_error.details["reason"],
            }
            if settings.KYC_CARD_DETECTOR_REQUIRED:
                raise self._detector_error
            return None

    def _onnx_providers(self) -> list[str]:
        try:
            import onnxruntime
        except ImportError as exc:
            raise ModelUnavailableError("card detector", "onnx_runtime_not_installed") from exc
        available = set(onnxruntime.get_available_providers())
        if settings.KYC_DEVICE == "cpu":
            return ["CPUExecutionProvider"]
        if "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if settings.KYC_DEVICE == "cuda":
            raise ModelUnavailableError("card detector", "cuda_provider_not_available")
        return ["CPUExecutionProvider"]

    def versions(self) -> dict[str, dict[str, Any]]:
        return {name: dict(value) for name, value in self._model_versions.items()}

    def readiness(self, *, load_models: bool = True) -> dict[str, Any]:
        checks: list[dict[str, str]] = []

        secret = str(settings.SECRET_KEY)
        secret_configured = (
            len(secret) >= 50
            and len(set(secret)) >= 5
            and secret != "replace-with-a-long-random-value"
            and not secret.startswith("django-insecure-")
        )
        checks.append(
            {
                "name": "secret_key",
                "status": "pass" if secret_configured else "fail",
                "reason": "configured" if secret_configured else "KYC_SECRET_KEY_not_configured",
            }
        )
        api_keys_configured = bool(configured_api_keys())
        checks.append(
            {
                "name": "api_authentication",
                "status": "pass" if api_keys_configured else "fail",
                "reason": "configured" if api_keys_configured else "KYC_API_KEYS_not_configured_or_insecure",
            }
        )
        checks.append(self._storage_readiness())

        if load_models:
            try:
                self.get_card_detector()
                detector_status = "pass"
                detector_reason = "custom_model_loaded" if self._detector else "opencv_baseline_available"
            except ModelUnavailableError as exc:
                detector_status, detector_reason = "fail", exc.details["reason"]
            checks.append({"name": "card_detector", "status": detector_status, "reason": detector_reason})

            try:
                reader = self.get_ocr_reader()
                ocr_status = "pass" if reader is not None else "unavailable"
                ocr_reason = "loaded" if reader is not None else "disabled"
            except ModelUnavailableError as exc:
                ocr_status = "fail" if settings.KYC_OCR_REQUIRED else "unavailable"
                ocr_reason = exc.details["reason"]
            checks.append({"name": "ocr", "status": ocr_status, "reason": ocr_reason})

        # Optional components may be explicitly unavailable while the worker is
        # still ready for a degraded, clearly labelled response.
        ready = all(check["status"] != "fail" for check in checks)
        return {"ready": ready, "checks": checks, "models": self.versions()}

    def _storage_readiness(self) -> dict[str, str]:
        try:
            root = validate_storage_root(
                Path(settings.KYC_PRIVATE_STORAGE_ROOT), create=True
            )
            with tempfile.NamedTemporaryFile(prefix=".readiness-", dir=root, delete=True):
                pass
            return {"name": "private_storage", "status": "pass", "reason": "writable"}
        except UnsafeStoragePathError:
            return {"name": "private_storage", "status": "fail", "reason": "unsafe_path"}
        except OSError:
            return {"name": "private_storage", "status": "fail", "reason": "not_writable"}


def _package_version(name: str, *, fallback: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return fallback


_registry: ModelRegistry | None = None
_registry_lock = threading.Lock()


def get_model_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ModelRegistry()
    return _registry


def reset_model_registry() -> None:
    """Testing/worker-reload hook; never call while serving active requests."""
    global _registry
    with _registry_lock:
        _registry = None
