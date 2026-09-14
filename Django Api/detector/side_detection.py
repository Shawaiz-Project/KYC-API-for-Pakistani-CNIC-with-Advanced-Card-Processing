from __future__ import annotations

import re
import threading
from typing import Any

import cv2

from .normalization import normalize_digits, normalize_text


_FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
_FACE_LOCK = threading.Lock()
_CNIC_CANDIDATE = re.compile(r"(?<!\d)(\d{5})[- ]?(\d{7})[- ]?(\d)(?!\d)")

_FRONT_TERMS = {
    "name",
    "father name",
    "husband name",
    "identity number",
    "date of birth",
    "date of issue",
    "نام",
    "ولدیت",
    "شناختی نمبر",
    "تاریخ پیدائش",
}
_BACK_TERMS = {
    "address",
    "permanent address",
    "date of expiry",
    "پتہ",
    "مستقل پتہ",
}


def classify_document_side(image, ocr_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Classify a corrected card using explainable, uncalibrated signals."""

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    with _FACE_LOCK:
        faces = _FACE_CASCADE.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(40, 40),
        )
    qr_payloads = _decode_qr_payloads(image)

    joined = " ".join(
        normalize_text(str(item.get("normalized_text") or item.get("raw_text") or "")).casefold()
        for item in (ocr_items or [])
    )
    front_terms = sum(term in joined for term in _FRONT_TERMS)
    back_terms = sum(term in joined for term in _BACK_TERMS)

    front_score = (0.75 if len(faces) else 0.0) + min(0.2, front_terms * 0.05)
    back_score = (0.9 if qr_payloads else 0.0) + min(0.1, back_terms * 0.05)

    if front_score >= 0.7 and back_score < 0.7:
        side, status, score = "front", "pass", min(front_score, 1.0)
    elif back_score >= 0.7 and front_score < 0.7:
        side, status, score = "back", "pass", min(back_score, 1.0)
    else:
        side, status, score = "unknown", "uncertain", max(front_score, back_score)

    qr_cnic = None
    for payload in qr_payloads:
        match = _CNIC_CANDIDATE.search(normalize_digits(payload))
        if match:
            qr_cnic = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
            break

    return {
        "detected_side": side,
        "status": status,
        "confidence": {
            "value": round(float(score), 4),
            "type": "heuristic_score",
            "calibrated": False,
        },
        "signals": {
            "face_count": int(len(faces)),
            "qr_count": len(qr_payloads),
            "front_keyword_count": int(front_terms),
            "back_keyword_count": int(back_terms),
        },
        # Do not expose or retain the full QR payload. Only a syntactically
        # recognized CNIC candidate is made available as field evidence.
        "qr_cnic": qr_cnic,
    }


def _decode_qr_payloads(image) -> list[str]:
    detector = cv2.QRCodeDetector()
    payloads: list[str] = []
    try:
        ok, decoded, _points, _straight = detector.detectAndDecodeMulti(image)
        if ok:
            payloads.extend(text for text in decoded if text)
    except (cv2.error, ValueError):
        pass
    if payloads:
        return payloads
    try:
        decoded, _points, _straight = detector.detectAndDecode(image)
        if decoded:
            payloads.append(decoded)
    except (cv2.error, ValueError):
        pass
    return payloads
