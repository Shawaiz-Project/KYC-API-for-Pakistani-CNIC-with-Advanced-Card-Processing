from __future__ import annotations

from .base import Detector, DetectorInput, DetectorResult


class DocumentConsistencyDetector(Detector):
    name = "document_consistency"
    version = "1.0"

    def detect(self, data: DetectorInput) -> DetectorResult:
        result = data.phase1_result
        if not result:
            return self.unavailable("phase1_result_missing")
        reasons: list[str] = []
        evidence: list[dict] = []
        sides = result.get("document", {}).get("detected_sides", {})
        front = sides.get("front_upload", {}).get("detected_side")
        back = sides.get("back_upload", {}).get("detected_side")
        evidence.append({"type": "detected_sides", "front": front, "back": back})
        if front and back and front == back:
            reasons.append("repeated_document_side")
        validation = result.get("validation", {}).get("checks", {})
        side_check = validation.get("side_consistency", {})
        if side_check.get("status") == "fail":
            reasons.append("front_back_identifier_conflict")
            evidence.append({"type": "validation_check", "check": "side_consistency", "code": side_check.get("code")})
        layout = result.get("document", {}).get("layout")
        if layout not in {"generic", "cnic_old", "cnic_new", None}:
            reasons.append("incompatible_document_layout")
        status = "fail" if reasons else "pass"
        if front not in {"front", None} or back not in {"back", None}:
            status = "fail"
            reasons.append("wrong_document_side")
        elif front is None or back is None:
            status = "uncertain"
            reasons.append("document_side_uncertain")
        return DetectorResult(
            detector=self.name,
            execution_status="completed",
            status=status,
            detector_version=self.version,
            reason_codes=sorted(set(reasons)) or ["document_consistent"],
            evidence=evidence,
            model_version="phase1-layout-rules-v1",
        )


class LayoutLandmarkDetector(Detector):
    name = "layout_landmarks"
    version = "0.3-review-signal"
    policy_relevant = False

    def detect(self, data: DetectorInput) -> DetectorResult:
        if not data.phase1_result:
            return self.unavailable("phase1_result_missing")
        sides = data.phase1_result.get("document", {}).get("detected_sides", {})
        front_signals = sides.get("front_upload", {}).get("signals", {})
        raw_ocr = data.phase1_result.get("ocr", {}).get("raw_detections", {})
        portrait = int(front_signals.get("face_count", 0)) >= 1
        text = bool(raw_ocr.get("front")) and bool(raw_ocr.get("back"))
        reasons = []
        if not portrait:
            reasons.append("expected_portrait_not_observed")
        if not text:
            reasons.append("expected_text_regions_not_observed")
        reasons.append("logo_chip_signature_models_require_annotated_training_data")
        return DetectorResult(
            detector=self.name,
            execution_status="completed",
            status="uncertain",
            detector_version=self.version,
            reason_codes=reasons,
            evidence=[
                {"landmark": "portrait", "status": "observed" if portrait else "not_observed", "artifact": data.artifact_refs.get("front")},
                {"landmark": "text_regions", "status": "observed" if text else "not_observed", "artifacts": [data.artifact_refs.get("front"), data.artifact_refs.get("back")]},
                {"landmark": "logo", "status": "unavailable"},
                {"landmark": "chip", "status": "unavailable"},
                {"landmark": "signature", "status": "unavailable"},
            ],
            model_version="phase1-side-signals+ocr-presence",
            policy_relevant=False,
        )
