from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
import urllib.error
import urllib.request
from datetime import timedelta
from urllib.parse import urlparse

from celery import shared_task
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone

from .models import WebhookDelivery, WebhookEndpoint, WebhookEvent


class UnsafeWebhookURL(ValueError):
    pass


def validate_webhook_url(url: str) -> None:
    parsed = urlparse(url)
    allowed_schemes = {"https"} | ({"http"} if settings.KYC_WEBHOOK_ALLOW_HTTP else set())
    if parsed.scheme not in allowed_schemes or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeWebhookURL("Webhook URL must use an allowed scheme and cannot contain credentials")
    if parsed.port not in {None, 443, 80}:
        raise UnsafeWebhookURL("Webhook URL port is not allowed")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise UnsafeWebhookURL("Webhook hostname could not be resolved") from exc
    if not addresses:
        raise UnsafeWebhookURL("Webhook hostname did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeWebhookURL("Webhook destinations must resolve only to public addresses")


def _fernet() -> Fernet:
    if not settings.KYC_WEBHOOK_ENCRYPTION_KEY:
        raise RuntimeError("KYC_WEBHOOK_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(settings.KYC_WEBHOOK_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError("KYC_WEBHOOK_ENCRYPTION_KEY is invalid") from exc


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Webhook secret could not be decrypted") from exc


def signature(secret: str, timestamp: int, body: bytes) -> str:
    signed = str(timestamp).encode() + b"." + body
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def create_event(organization, event_type: str, payload: dict) -> WebhookEvent:
    event = WebhookEvent.objects.create(organization=organization, event_type=event_type, payload=payload)
    for endpoint in organization.webhook_endpoints.filter(is_active=True):
        if event_type in endpoint.event_types or "*" in endpoint.event_types:
            delivery = WebhookDelivery.objects.create(endpoint=endpoint, event=event)
            transaction = deliver_webhook.delay(delivery.pk)
            if not transaction.id:
                delivery.error_code = "dispatch_identifier_unavailable"
                delivery.save(update_fields=("error_code", "updated_at"))
    return event


@shared_task(bind=True, max_retries=4)
def deliver_webhook(self, delivery_id: int):
    delivery = WebhookDelivery.objects.select_related("endpoint", "event").get(pk=delivery_id)
    endpoint = delivery.endpoint
    try:
        validate_webhook_url(endpoint.url)
        body = json.dumps(
            {"id": str(delivery.event_id), "type": delivery.event.event_type, "created_at": delivery.event.created_at.isoformat(), "data": delivery.event.payload},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        timestamp = int(time.time())
        request = urllib.request.Request(
            endpoint.url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Shanakht-Webhooks/1.0",
                "X-Shanakht-Event-ID": str(delivery.event_id),
                "X-Shanakht-Timestamp": str(timestamp),
                "X-Shanakht-Signature": f"v1={signature(decrypt_secret(endpoint.secret_ciphertext), timestamp, body)}",
            },
        )
        with urllib.request.urlopen(request, timeout=settings.KYC_WEBHOOK_TIMEOUT_SECONDS) as response:
            response_status = response.status
        if not 200 <= response_status < 300:
            raise urllib.error.HTTPError(endpoint.url, response_status, "non-success", {}, None)
    except (UnsafeWebhookURL, RuntimeError) as exc:
        delivery.state = WebhookDelivery.State.FAILED
        delivery.error_code = type(exc).__name__
        delivery.attempts += 1
        delivery.save()
        return {"state": "failed", "error_code": delivery.error_code}
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        delivery.attempts += 1
        delivery.response_status = getattr(exc, "code", None)
        delivery.error_code = type(exc).__name__
        if self.request.retries >= self.max_retries:
            delivery.state = WebhookDelivery.State.FAILED
        else:
            delivery.next_attempt_at = timezone.now() + timedelta(seconds=min(300, 2 ** self.request.retries * 10))
        delivery.save()
        if delivery.state != WebhookDelivery.State.FAILED:
            raise self.retry(exc=exc, countdown=min(300, 2 ** self.request.retries * 10))
        return {"state": "failed"}
    delivery.state = WebhookDelivery.State.DELIVERED
    delivery.attempts += 1
    delivery.response_status = response_status
    delivery.error_code = ""
    delivery.next_attempt_at = None
    delivery.save()
    return {"state": "delivered", "status": response_status}


def new_webhook_secret() -> str:
    return secrets.token_urlsafe(32)
