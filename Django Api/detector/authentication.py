from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


_MINIMUM_API_KEY_LENGTH = 24
_REJECTED_EXAMPLE_KEYS = frozenset(
    {
        "replace-with-a-random-api-key",
        "change-me",
        "changeme",
        "example",
    }
)


def configured_api_keys() -> tuple[str, ...]:
    """Return only non-placeholder keys with a defensible minimum length."""

    return tuple(
        key
        for key in settings.KYC_API_KEYS
        if len(key) >= _MINIMUM_API_KEY_LENGTH and key.casefold() not in _REJECTED_EXAMPLE_KEYS
    )


@dataclass(frozen=True)
class APIKeyPrincipal:
    """Anonymous-looking principal keyed by a non-reversible identifier."""

    pk: str
    is_authenticated: bool = True
    is_anonymous: bool = False

    @property
    def username(self) -> str:
        return "api-key"


class APIKeyAuthentication(BaseAuthentication):
    """Authenticate processing requests with an operator-configured API key."""

    def authenticate(self, request):
        configured = configured_api_keys()
        if not configured:
            raise AuthenticationFailed(
                {"code": "authentication_unavailable", "message": "API key authentication is not configured."}
            )

        header_name = settings.KYC_API_KEY_HEADER
        provided = request.headers.get(header_name)
        if not provided:
            return None

        matched = any(secrets.compare_digest(provided, candidate) for candidate in configured)
        if not matched:
            raise AuthenticationFailed({"code": "invalid_api_key", "message": "The API key is invalid."})

        identifier = hashlib.sha256(provided.encode("utf-8")).hexdigest()
        return APIKeyPrincipal(pk=identifier), None

    def authenticate_header(self, request):
        return f'ApiKey header="{settings.KYC_API_KEY_HEADER}"'
