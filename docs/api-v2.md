# Phase 2/3 API contract

All `/api/v2/` responses carry `X-Request-ID` and `Cache-Control: no-store`.
They accept a Django session or a database-backed organization API key. API
keys have scopes, can be revoked/rotated, and never grant access outside their
organization. User queries are also constrained by active organization
membership; applicants see only their own applications.

## Application flow

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v2/applications` | Create a draft; `Idempotency-Key` makes retries deterministic. |
| POST | `/api/v2/applications/{id}/artifacts` | Upload one `front`, `back`, or `selfie` private artifact. |
| POST | `/api/v2/applications/{id}/consent` | Record explicit, versioned biometric/document consent. |
| POST | `/api/v2/applications/{id}/liveness-sessions` | Issue a short-lived randomized challenge. |
| POST | `/api/v2/liveness-sessions/{id}/captures` | Submit the next action capture and challenge token. |
| POST | `/api/v2/liveness-sessions/{id}/complete` | Consume the challenge or request the manual-review alternative. |
| POST | `/api/v2/applications/{id}/submit` | Queue idempotent processing. |
| GET | `/api/v2/applications/{id}` | Retrieve processing state, fields, evidence, checks, and decisions. |
| POST | `/api/v2/applications/{id}/corrections` | Reviewer-only OCR correction; raw extraction remains immutable. |
| POST | `/api/v2/applications/{id}/decisions` | Reviewer-only traceable decision. |
| POST | `/api/v2/applications/{id}/assignment` | Assign an in-organization reviewer/admin. |
| GET | `/api/v2/media/{artifact_id}` | Authorized, private, no-store media stream. |
| GET/POST | `/api/v2/api-keys` | Admin-only usage listing and one-time key issuance. |
| POST | `/api/v2/api-keys/{id}/actions` | Admin-only `rotate` or `revoke`. |
| GET/POST | `/api/v2/webhooks` | Admin-only endpoint listing/creation. |
| GET | `/api/v2/metrics` | Admin-only Prometheus metrics without sensitive labels. |

Processing state is `draft`, `queued`, `processing`, `completed`, or `failed`.
The independent decision outcome is `checks_passed`, `checks_failed`,
`needs_recapture`, or `needs_review`. A required check that is disabled,
unavailable, failed to execute, or uncertain can never produce
`checks_passed`.

Every detector result contains:

```json
{
  "detector": "face_comparison",
  "execution_status": "unavailable",
  "status": "unavailable",
  "score": null,
  "threshold": null,
  "reason_codes": ["face_recognition_model_missing_or_checksum_mismatch"],
  "evidence": [],
  "model_version": null,
  "detector_version": "1.0",
  "execution_ms": 0.42,
  "experimental": false
}
```

`score`, when present, includes a score type and
`calibrated_probability: false`. No combined fraud probability is returned.
Authoritative-provider results are a separate object and remain `unavailable`
until a real, authorized provider adapter is configured.

## Python example

```python
import requests

base = "https://staging.example.com/api/v2"
headers = {"X-API-Key": "<organization-api-key>", "Idempotency-Key": "case-2026-001"}
application = requests.post(f"{base}/applications", headers=headers, json={"external_reference": "case-001"}).json()
for kind, path in {"front": "front.jpg", "back": "back.jpg", "selfie": "selfie.jpg"}.items():
    with open(path, "rb") as image:
        response = requests.post(
            f"{base}/applications/{application['id']}/artifacts",
            headers={"X-API-Key": headers["X-API-Key"]},
            files={"file": image},
            data={"kind": kind},
        )
        response.raise_for_status()
requests.post(f"{base}/applications/{application['id']}/consent", headers=headers, json={"accepted": True, "policy_version": "phase3-consent-v1"}).raise_for_status()
requests.post(f"{base}/applications/{application['id']}/submit", headers=headers, json={}).raise_for_status()
result = requests.get(f"{base}/applications/{application['id']}", headers=headers).json()
```

## JavaScript example

```javascript
const base = "/api/v2";
const headers = {"X-API-Key": apiKey, "Content-Type": "application/json"};
const application = await fetch(`${base}/applications`, {
  method: "POST", headers: {...headers, "Idempotency-Key": "case-2026-001"},
  body: JSON.stringify({external_reference: "case-001"})
}).then(response => response.json());

const data = new FormData();
data.append("kind", "front");
data.append("file", frontFile);
await fetch(`${base}/applications/${application.id}/artifacts`, {
  method: "POST", headers: {"X-API-Key": apiKey}, body: data
});
```

## Webhooks

Administrators create endpoints at `POST /api/v2/webhooks`. The secret is
returned once and encrypted at rest. Each delivery sends an event ID, Unix
timestamp, and `X-Shanakht-Signature: v1=<hex HMAC-SHA256>`. Verify the exact
body against `timestamp + "." + body`, reject stale timestamps, and store event
IDs to reject replay. HTTPS and public DNS destinations are required by default;
private, loopback, link-local, reserved, credential-bearing, and nonstandard-port
destinations are rejected and DNS is checked again at delivery time.

The generated OpenAPI document is [openapi.yaml](openapi.yaml). The legacy v1
contract is unchanged and remains documented in [api.md](api.md).
