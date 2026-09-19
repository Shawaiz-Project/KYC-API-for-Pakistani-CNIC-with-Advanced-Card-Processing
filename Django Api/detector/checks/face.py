from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings

from .base import Detector, DetectorInput, DetectorResult


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verified_model(path: Path, expected: str) -> bool:
    return path.is_file() and bool(expected) and _sha256(path) == expected


def _basic_quality(image: np.ndarray) -> tuple[list[str], dict]:
    if image is None or image.size == 0:
        return ["selfie_decode_failed"], {}
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    reasons = []
    if min(width, height) < 480:
        reasons.append("selfie_resolution_too_low")
    if blur < settings.KYC_BLUR_THRESHOLD:
        reasons.append("selfie_blurry")
    if mean < settings.KYC_DARK_MEAN_THRESHOLD:
        reasons.append("selfie_underexposed")
    if mean > settings.KYC_BRIGHT_MEAN_THRESHOLD:
        reasons.append("selfie_overexposed")
    return reasons, {"width": width, "height": height, "mean_luminance": round(mean, 3), "laplacian_variance": round(blur, 3)}


class SelfieQualityDetector(Detector):
    name = "selfie_quality"
    version = "1.0"

    def detect(self, data: DetectorInput) -> DetectorResult:
        if data.selfie_image is None:
            return self.unavailable("selfie_missing")
        reasons, metrics = _basic_quality(data.selfie_image)
        cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(str(cascade_path))
        gray = cv2.cvtColor(data.selfie_image, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        metrics["face_count"] = len(faces)
        if len(faces) == 0:
            reasons.append("no_face_detected")
        elif len(faces) > 1:
            reasons.append("multiple_faces_detected")
        model_path = Path(settings.KYC_FACE_DETECTOR_MODEL)
        if not _verified_model(model_path, settings.KYC_FACE_DETECTOR_SHA256):
            reasons.extend(("pose_check_unavailable", "obstruction_check_unavailable"))
        status = "fail" if any(reason.startswith("selfie_") or reason in {"no_face_detected", "multiple_faces_detected"} for reason in reasons) else "uncertain" if reasons else "pass"
        return DetectorResult(
            detector=self.name,
            execution_status="completed",
            status=status,
            detector_version=self.version,
            reason_codes=reasons or ["selfie_quality_sufficient"],
            evidence=[{"type": "selfie_quality_metrics", **metrics, "artifact": data.artifact_refs.get("selfie")}],
            model_version=f"opencv-haar-{cv2.__version__}",
        )


class FaceComparisonDetector(Detector):
    name = "face_comparison"
    version = "1.0"

    def detect(self, data: DetectorInput) -> DetectorResult:
        if data.front_image is None or data.selfie_image is None:
            return self.unavailable("comparison_images_missing")
        detector_path = Path(settings.KYC_FACE_DETECTOR_MODEL)
        recognizer_path = Path(settings.KYC_FACE_RECOGNITION_MODEL)
        if not _verified_model(detector_path, settings.KYC_FACE_DETECTOR_SHA256):
            return self.unavailable("face_detector_model_missing_or_checksum_mismatch")
        if not _verified_model(recognizer_path, settings.KYC_FACE_RECOGNITION_SHA256):
            return self.unavailable("face_recognition_model_missing_or_checksum_mismatch")
        detector = cv2.FaceDetectorYN.create(str(detector_path), "", (320, 320), 0.85, 0.3, 5000)
        recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")
        faces = []
        for image in (data.front_image, data.selfie_image):
            detector.setInputSize((image.shape[1], image.shape[0]))
            _, found = detector.detect(image)
            if found is None or len(found) != 1:
                return DetectorResult(
                    detector=self.name,
                    execution_status="completed",
                    status="uncertain",
                    detector_version=self.version,
                    reason_codes=["face_count_unsuitable_for_comparison"],
                    model_version="OpenCV-Zoo-YuNet+SFace",
                )
            aligned = recognizer.alignCrop(image, found[0])
            faces.append(recognizer.feature(aligned))
        similarity = float(recognizer.match(faces[0], faces[1], cv2.FaceRecognizerSF_FR_COSINE))
        threshold = settings.KYC_FACE_MATCH_THRESHOLD
        margin = settings.KYC_FACE_UNCERTAIN_MARGIN
        if similarity >= threshold + margin:
            status, reason = "pass", "face_match"
        elif similarity < threshold - margin:
            status, reason = "fail", "face_non_match"
        else:
            status, reason = "uncertain", "face_match_near_threshold"
        return DetectorResult(
            detector=self.name,
            execution_status="completed",
            status=status,
            detector_version=self.version,
            score=round(similarity, 6),
            score_type="cosine_similarity_raw",
            threshold=threshold,
            reason_codes=[reason],
            evidence=[{"type": "image_pair", "front": data.artifact_refs.get("front"), "selfie": data.artifact_refs.get("selfie")}],
            model_version="OpenCV-Zoo-YuNet+SFace",
        )
