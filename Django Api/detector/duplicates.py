from __future__ import annotations

import hashlib
import hmac

import cv2
from django.conf import settings

from .models import DuplicateFingerprint


def perceptual_dhash(image) -> str:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = resized[:, 1:] > resized[:, :-1]
    value = sum(int(bit) << index for index, bit in enumerate(bits.flatten()))
    return f"{value:016x}"


def identifier_hmac(normalized_identifier: str) -> str | None:
    if not settings.KYC_IDENTIFIER_HMAC_KEY:
        return None
    return hmac.new(settings.KYC_IDENTIFIER_HMAC_KEY.encode(), normalized_identifier.encode(), hashlib.sha256).hexdigest()


def find_duplicate_signals(organization, application, sha256: str, dhash: str, identifier_digest: str | None = None) -> list[dict]:
    prior = DuplicateFingerprint.objects.filter(organization=organization).exclude(application=application)
    signals = []
    if sha256:
        for match in prior.filter(sha256=sha256)[:5]:
            signals.append({"reason": "identical_file", "application_id": str(match.application_id)})
    if dhash:
        for match in prior.filter(perceptual_hash=dhash)[:5]:
            signals.append({"reason": "perceptually_similar_document", "application_id": str(match.application_id)})
    if identifier_digest:
        for match in prior.filter(identifier_hmac=identifier_digest)[:5]:
            signals.append({"reason": "repeated_reliable_identifier", "application_id": str(match.application_id)})
    return signals
