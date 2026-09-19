from __future__ import annotations

import cv2

from .base import Detector, DetectorInput, DetectorResult


class LivenessDetector(Detector):
    name = "liveness"
    version = "1.0"

    def detect(self, data: DetectorInput) -> DetectorResult:
        if not data.liveness:
            return self.unavailable("liveness_session_missing")
        if data.liveness.get("expired") or data.liveness.get("replayed"):
            return DetectorResult(self.name, "completed", "fail", self.version, reason_codes=["expired_or_replayed_session"])
        if not data.liveness.get("actions_completed"):
            return DetectorResult(self.name, "completed", "uncertain", self.version, reason_codes=["action_tracking_incomplete"])
        if data.liveness.get("anti_spoof_status") != "pass":
            return DetectorResult(
                self.name,
                "completed" if data.liveness.get("anti_spoof_status") else "unavailable",
                "uncertain" if data.liveness.get("anti_spoof_status") else "unavailable",
                self.version,
                reason_codes=["anti_spoof_not_validated_or_unavailable"],
                model_version=data.liveness.get("anti_spoof_model"),
            )
        return DetectorResult(self.name, "completed", "pass", self.version, reason_codes=["action_and_anti_spoof_checks_passed"], model_version=data.liveness.get("anti_spoof_model"))


class TamperingDetector(Detector):
    name = "tampering"
    version = "0.2-experimental"
    experimental = True
    policy_relevant = False

    def detect(self, data: DetectorInput) -> DetectorResult:
        if data.front_image is None:
            return self.unavailable("document_image_missing")
        gray = cv2.cvtColor(data.front_image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 180)
        density = float((edges > 0).mean())
        suspicious = density < 0.01 or density > 0.35
        return DetectorResult(
            detector=self.name,
            execution_status="completed",
            status="uncertain" if suspicious else "pass",
            detector_version=self.version,
            score=round(density, 6),
            score_type="global_edge_density_heuristic",
            reason_codes=["unexpected_edge_density"] if suspicious else ["no_global_layout_anomaly_observed"],
            evidence=[{"type": "whole_document_region", "artifact": data.artifact_refs.get("front")}],
            model_version="opencv-canny-heuristic",
            experimental=True,
            policy_relevant=False,
        )


class DuplicateDetector(Detector):
    name = "duplicate"
    version = "1.0"
    policy_relevant = False

    def detect(self, data: DetectorInput) -> DetectorResult:
        signals = data.phase1_result.get("duplicate_signals", [])
        if not signals:
            return DetectorResult(self.name, "completed", "pass", self.version, reason_codes=["no_duplicate_signal"], policy_relevant=False)
        return DetectorResult(
            self.name,
            "completed",
            "uncertain",
            self.version,
            reason_codes=[item.get("reason", "duplicate_signal") for item in signals],
            evidence=signals,
            policy_relevant=False,
        )
