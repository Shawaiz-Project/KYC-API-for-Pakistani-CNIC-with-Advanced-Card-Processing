from __future__ import annotations

from rest_framework.exceptions import PermissionDenied

from .models import Membership, Organization


def request_organization(request) -> Organization:
    principal = request.user
    organization_id = getattr(principal, "organization_id", None)
    if organization_id:
        return Organization.objects.get(pk=organization_id, is_active=True)
    if not getattr(principal, "is_authenticated", False):
        raise PermissionDenied("Authentication is required.")
    memberships = Membership.objects.filter(user=principal, is_active=True, organization__is_active=True).select_related("organization")
    requested = request.headers.get("X-Organization-ID")
    if requested:
        memberships = memberships.filter(organization_id=requested)
    membership = memberships.first()
    if membership is None:
        raise PermissionDenied("No active organization membership is available.")
    return membership.organization


def request_membership(request, organization: Organization | None = None) -> Membership | None:
    if not getattr(request.user, "pk", None) or hasattr(request.user, "scopes"):
        return None
    organization = organization or request_organization(request)
    return Membership.objects.filter(user=request.user, organization=organization, is_active=True).first()


def require_role(request, *roles: str) -> Membership:
    membership = request_membership(request)
    if membership is None or membership.role not in roles:
        raise PermissionDenied("The active organization role does not permit this action.")
    return membership


def require_scope(request, scope: str) -> None:
    scopes = getattr(request.user, "scopes", None)
    if scopes is not None and scope not in scopes and "*" not in scopes:
        raise PermissionDenied("The API key does not include the required scope.")
