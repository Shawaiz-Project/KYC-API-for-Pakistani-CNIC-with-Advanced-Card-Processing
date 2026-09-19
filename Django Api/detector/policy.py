from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason_codes: list[str]
    policy_version: str

    def as_dict(self) -> dict:
        return {"outcome": self.outcome, "reason_codes": self.reason_codes, "policy_version": self.policy_version}


def decide(results: list[dict], required: list[str] | tuple[str, ...] | None = None) -> Decision:
    required_names = set(required if required is not None else settings.KYC_REQUIRED_CHECKS)
    by_name = {item["detector"]: item for item in results}
    reasons: list[str] = []

    for name in required_names:
        result = by_name.get(name)
        if result is None or result.get("execution_status") in {"disabled", "unavailable", "failed"}:
            reasons.append(f"required_check_unavailable:{name}")
    if reasons:
        return Decision("needs_review", reasons, settings.KYC_POLICY_VERSION)

    failed = [name for name in required_names if by_name[name].get("status") == "fail"]
    recapture_codes = {
        "selfie_resolution_too_low", "selfie_blurry", "selfie_underexposed", "selfie_overexposed",
        "no_face_detected", "multiple_faces_detected", "wrong_document_side", "document_side_uncertain",
    }
    if failed:
        failure_reasons = [code for name in failed for code in by_name[name].get("reason_codes", [])]
        outcome = "needs_recapture" if any(code in recapture_codes for code in failure_reasons) else "checks_failed"
        return Decision(outcome, failure_reasons, settings.KYC_POLICY_VERSION)

    uncertain = [name for name in required_names if by_name[name].get("status") != "pass"]
    if uncertain:
        return Decision("needs_review", [f"required_check_uncertain:{name}" for name in uncertain], settings.KYC_POLICY_VERSION)

    return Decision("checks_passed", ["all_required_checks_passed"], settings.KYC_POLICY_VERSION)
