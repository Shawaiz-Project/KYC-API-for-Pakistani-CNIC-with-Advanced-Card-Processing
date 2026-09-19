from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


EXECUTION_STATUSES = frozenset({"disabled", "unavailable", "failed", "completed"})
CHECK_STATUSES = frozenset({"pass", "fail", "uncertain", "not_run", "unavailable"})


@dataclass
class DetectorResult:
    detector: str
    execution_status: str
    status: str
    detector_version: str
    score: float | None = None
    score_type: str | None = None
    threshold: float | None = None
    reason_codes: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    model_version: str | None = None
    execution_ms: float = 0.0
    experimental: bool = False
    policy_relevant: bool = True

    def __post_init__(self) -> None:
        if self.execution_status not in EXECUTION_STATUSES:
            raise ValueError("unsupported detector execution status")
        if self.status not in CHECK_STATUSES:
            raise ValueError("unsupported check status")
        if self.score is not None and not self.score_type:
            raise ValueError("scored checks must identify the score type")

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["score"] = None if self.score is None else {
            "value": self.score,
            "type": self.score_type,
            "calibrated_probability": False,
        }
        return value


@dataclass
class DetectorInput:
    application: Any = None
    front_image: Any = None
    back_image: Any = None
    selfie_image: Any = None
    phase1_result: dict[str, Any] = field(default_factory=dict)
    liveness: dict[str, Any] = field(default_factory=dict)
    artifact_refs: dict[str, str] = field(default_factory=dict)


class Detector(ABC):
    name = "detector"
    version = "1"
    experimental = False
    policy_relevant = True

    @abstractmethod
    def detect(self, data: DetectorInput) -> DetectorResult:
        raise NotImplementedError

    def run(self, data: DetectorInput) -> DetectorResult:
        started = time.perf_counter()
        try:
            result = self.detect(data)
        except Exception as exc:  # detector failures must be explicit and isolated
            result = DetectorResult(
                detector=self.name,
                execution_status="failed",
                status="uncertain",
                detector_version=self.version,
                reason_codes=[f"detector_error:{type(exc).__name__}"],
                experimental=self.experimental,
                policy_relevant=self.policy_relevant,
            )
        result.execution_ms = round((time.perf_counter() - started) * 1000, 3)
        return result

    def unavailable(self, reason: str, *, model_version: str | None = None) -> DetectorResult:
        return DetectorResult(
            detector=self.name,
            execution_status="unavailable",
            status="unavailable",
            detector_version=self.version,
            reason_codes=[reason],
            model_version=model_version,
            experimental=self.experimental,
            policy_relevant=self.policy_relevant,
        )
