from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    status: str
    reason_code: str
    reference: str | None = None


class UnavailableAuthoritativeProvider:
    name = "unavailable"

    def verify(self, _application) -> ProviderResult:
        return ProviderResult(self.name, "unavailable", "authorized_provider_not_configured")


def get_authoritative_provider():
    # Real providers must be added by name only after access, documentation,
    # credentials, data-protection review, and contract tests exist.
    return UnavailableAuthoritativeProvider()
