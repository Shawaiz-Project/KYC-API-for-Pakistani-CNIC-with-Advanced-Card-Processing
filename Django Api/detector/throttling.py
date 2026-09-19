from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache
from rest_framework.throttling import BaseThrottle


class OrganizationQuotaThrottle(BaseThrottle):
    """Fixed-minute quota for database API clients and authenticated users."""

    def __init__(self):
        self.remaining_seconds = 60

    def allow_request(self, request, view):
        auth = getattr(request, "auth", None)
        if auth is not None and hasattr(auth, "quota_per_minute"):
            identity = f"key:{auth.pk}"
            limit = auth.quota_per_minute
        elif getattr(request.user, "is_authenticated", False):
            identity = f"user:{request.user.pk}"
            try:
                limit = int(settings.KYC_RATE_LIMIT.split("/", 1)[0])
            except ValueError:
                limit = 30
        else:
            return True
        window = int(time.time() // 60)
        self.remaining_seconds = 60 - int(time.time() % 60)
        key = f"kyc-quota:{identity}:{window}"
        if cache.add(key, 1, timeout=65):
            count = 1
        else:
            try:
                count = cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=65)
                count = 1
        return count <= max(1, int(limit))

    def wait(self):
        return self.remaining_seconds
