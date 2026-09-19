from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
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


@dataclass(frozen=True)
class OrganizationAPIKeyPrincipal:
    pk: str
    organization_id: object
    scopes: tuple[str, ...]
    is_authenticated: bool = True
    is_anonymous: bool = False

    @property
    def username(self) -> str:
        return "organization-api-client"


class OrganizationAPIKeyAuthentication(BaseAuthentication):
    """Database-backed, rotatable, organization-scoped Phase 3 API keys."""

    def authenticate(self, request):
        from .models import APIClientKey

        provided = request.headers.get(settings.KYC_API_KEY_HEADER)
        if not provided:
            return None
        digest = hashlib.sha256(provided.encode("utf-8")).hexdigest()
        prefix = provided[:12]
        try:
            key = APIClientKey.objects.select_related("organization").get(
                prefix=prefix, digest=digest, is_active=True, organization__is_active=True
            )
        except APIClientKey.DoesNotExist as exc:
            raise AuthenticationFailed({"code": "invalid_api_key", "message": "The API key is invalid."}) from exc
        with transaction.atomic():
            APIClientKey.objects.filter(pk=key.pk).update(usage_count=F("usage_count") + 1, last_used_at=timezone.now())
        principal = OrganizationAPIKeyPrincipal(str(key.pk), key.organization_id, tuple(key.scopes))
        return principal, key

    def authenticate_header(self, request):
        return f'ApiKey header="{settings.KYC_API_KEY_HEADER}"'


def issue_organization_api_key(organization, name: str, scopes: list[str], quota_per_minute: int = 30) -> tuple[object, str]:
    """Create a key and return its plaintext exactly once."""

    from .models import APIClientKey

    plaintext = f"sk_kyc_{secrets.token_urlsafe(32)}"
    record = APIClientKey.objects.create(
        organization=organization,
        name=name,
        prefix=plaintext[:12],
        digest=hashlib.sha256(plaintext.encode()).hexdigest(),
        scopes=scopes,
        quota_per_minute=max(1, min(int(quota_per_minute), 10_000)),
    )
    return record, plaintext
