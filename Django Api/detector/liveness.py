from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import status
import cv2
from pathlib import Path

from .errors import KYCError
from .models import LivenessSession


def create_session(application, user):
    choices = list(settings.KYC_LIVENESS_ACTIONS)
    if len(choices) < 2:
        choices = ["turn_left", "turn_right", "look_center"]
    movement_choices = [item for item in choices if item != "look_center"] or ["turn_left", "turn_right"]
    selected = [secrets.choice(movement_choices), "look_center"]
    token = secrets.token_urlsafe(32)
    session = LivenessSession.objects.create(
        application=application,
        user=user if getattr(user, "pk", None) else None,
        actions=selected,
        challenge_digest=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=timezone.now() + timedelta(seconds=settings.KYC_LIVENESS_SESSION_SECONDS),
    )
    return session, token


def validate_challenge(session: LivenessSession, token: str) -> None:
    now = timezone.now()
    if session.expires_at <= now:
        if session.state == LivenessSession.State.ACTIVE:
            session.state = LivenessSession.State.EXPIRED
            session.save(update_fields=("state", "updated_at"))
        raise KYCError("liveness_session_expired", "The liveness session has expired.", status.HTTP_409_CONFLICT)
    if session.state != LivenessSession.State.ACTIVE:
        raise KYCError("liveness_session_not_reusable", "The liveness session cannot be reused.", status.HTTP_409_CONFLICT)
    candidate = hashlib.sha256(token.encode()).hexdigest()
    if not secrets.compare_digest(candidate, session.challenge_digest):
        raise KYCError("invalid_liveness_challenge", "The liveness challenge is invalid.", status.HTTP_403_FORBIDDEN)


def landmark_action_status(_image, _action: str) -> tuple[str, dict]:
    from .checks.face import _verified_model

    path = Path(settings.KYC_FACE_DETECTOR_MODEL)
    if not _verified_model(path, settings.KYC_FACE_DETECTOR_SHA256):
        return "unavailable", {"reason": "server_landmark_model_not_configured"}
    detector = cv2.FaceDetectorYN.create(str(path), "", (320, 320), 0.85, 0.3, 5000)
    detector.setInputSize((_image.shape[1], _image.shape[0]))
    _, faces = detector.detect(_image)
    if faces is None or len(faces) != 1:
        return "fail", {"reason": "liveness_face_count_invalid", "face_count": 0 if faces is None else len(faces)}
    face = faces[0]
    left_eye_x, right_eye_x, nose_x = float(face[4]), float(face[6]), float(face[8])
    eye_span = max(abs(right_eye_x - left_eye_x), 1.0)
    relative_nose = (nose_x - min(left_eye_x, right_eye_x)) / eye_span
    if _action == "turn_left":
        passed = relative_nose < 0.42
    elif _action == "turn_right":
        passed = relative_nose > 0.58
    elif _action == "look_center":
        passed = 0.42 <= relative_nose <= 0.58
    else:
        return "fail", {"reason": "unsupported_liveness_action"}
    return ("pass" if passed else "fail"), {
        "reason": "landmark_action_observed" if passed else "landmark_action_not_observed",
        "relative_nose_position": round(relative_nose, 4),
        "model_version": "OpenCV-Zoo-YuNet",
        "raw_score_is_calibrated_probability": False,
    }


def anti_spoof_status(_image) -> tuple[str, str | None]:
    # A bare ONNX path is intentionally insufficient: input preprocessing,
    # output semantics, license, checksum, and evaluation must all be recorded.
    return "unavailable", None
