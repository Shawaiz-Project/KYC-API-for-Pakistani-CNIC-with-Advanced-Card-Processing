from __future__ import annotations

from django.conf import settings

from .base import Detector, DetectorInput, DetectorResult
from .document import DocumentConsistencyDetector, LayoutLandmarkDetector
from .face import FaceComparisonDetector, SelfieQualityDetector
from .signals import DuplicateDetector, LivenessDetector, TamperingDetector


DETECTOR_CLASSES: dict[str, type[Detector]] = {
    "document_consistency": DocumentConsistencyDetector,
    "layout_landmarks": LayoutLandmarkDetector,
    "selfie_quality": SelfieQualityDetector,
    "face_comparison": FaceComparisonDetector,
    "liveness": LivenessDetector,
    "tampering": TamperingDetector,
    "duplicate": DuplicateDetector,
}


class DetectorRegistry:
    def __init__(self, enabled: list[str] | tuple[str, ...] | None = None):
        self.enabled = tuple(enabled if enabled is not None else settings.KYC_ENABLED_DETECTORS)

    def results(self, data: DetectorInput) -> list[DetectorResult]:
        results = []
        for name, detector_type in DETECTOR_CLASSES.items():
            if name not in self.enabled:
                results.append(DetectorResult(name, "disabled", "not_run", detector_type.version, reason_codes=["disabled_by_configuration"]))
            else:
                results.append(detector_type().run(data))
        return results


def run_configured_detectors(data: DetectorInput) -> list[dict]:
    return [result.as_dict() for result in DetectorRegistry().results(data)]
