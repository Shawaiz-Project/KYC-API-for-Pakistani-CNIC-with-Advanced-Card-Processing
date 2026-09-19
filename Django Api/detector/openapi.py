from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import serializers
from rest_framework.views import APIView
from .throttling import OrganizationQuotaThrottle


class EmptySerializer(serializers.Serializer):
    """Fallback for manually documented APIViews without a model serializer."""


class KYCAPIView(APIView):
    serializer_class = EmptySerializer
    throttle_classes = [OrganizationQuotaThrottle]


class LegacyAPIKeyScheme(OpenApiAuthenticationExtension):
    target_class = "detector.authentication.APIKeyAuthentication"
    name = "legacyApiKey"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "X-API-Key"}


class OrganizationAPIKeyScheme(OpenApiAuthenticationExtension):
    target_class = "detector.authentication.OrganizationAPIKeyAuthentication"
    name = "organizationApiKey"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "X-API-Key"}
