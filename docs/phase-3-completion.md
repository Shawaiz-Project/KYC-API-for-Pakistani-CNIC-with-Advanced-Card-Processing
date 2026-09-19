# Phase 3 completion report

## Working implementation

- Responsive React/TypeScript applicant and reviewer interfaces follow the
  supplied Shanakht visual direction, support English/Urdu direction changes,
  camera denial/upload fallback, immediate client feedback, explicit consent,
  evidence views, OCR correction, and review decisions. Images use ephemeral
  object URLs and are excluded from analytics and persistent browser storage.
- PostgreSQL-selectable Django persistence covers organizations, roles,
  applications, private artifact metadata, extraction revisions, checks,
  consent, decisions, audit events, jobs, liveness, duplicate fingerprints,
  API clients, authoritative results, and webhook history. SQLite remains the
  tested local-development profile.
- Private filesystem and S3-compatible object-store adapters never publish a
  media URL. Every read passes organization/application authorization and is
  streamed with private/no-store headers.
- Celery/Redis jobs use late acknowledgement, worker-loss rejection, bounded
  retry, task timeouts, row locks, state transitions, and idempotent completed
  job handling. Eager mode makes a fresh local install reproducible.
- Database API keys are organization scoped, hash-only at rest, scoped,
  rotatable/revocable, and usage-counted. Session users are constrained by
  membership and role.
- Signed webhooks have event IDs, timestamps, delivery history, bounded retries,
  HMAC signatures, encrypted secrets, and SSRF-resistant destination checks.
- OpenAPI/Swagger endpoints, Python/JavaScript examples, protected Prometheus
  metrics, Docker/Compose files, CI, staging settings, retention cleanup, admin
  bootstrap, and operations documentation are present.
- A CNIC document registry is supported. Passport TD3/MRZ and the specifically
  named Pakistan Punjab driving-license v1 format are disabled pilots. MRZ check
  digits, if enabled and evaluated, prove only internal MRZ consistency—not
  authenticity. The authoritative-provider interface returns unavailable and
  never simulates a provider response.

## Verification and blockers

- The existing Phase 1 contract remains covered by its compatibility tests.
- Backend and frontend automated tests pass; the production frontend build
  succeeds; Django migrations and OpenAPI validation succeed.
- Docker is not installed on the acceptance workstation, so Compose startup,
  PostgreSQL backup restoration, Redis worker crash recovery, and container
  rollback could not be executed here. The exact commands and pass criteria are
  documented in [deployment.md](deployment.md); no demonstration is claimed.
- No authorized object-store, authoritative-provider, email, public hostname,
  TLS certificate, or deployment credential was supplied. Public deployment
  remains a separately reviewable action and was not performed.
- No consented held-out evaluation data or licensed/approved face,
  landmark, or anti-spoof weights were supplied. Accuracy, throughput, and p95
  inference latency on named production hardware are therefore not claimed.
- The requested local administrator was provisioned interactively in the
  ignored local database. Its password was not written to code, docs, fixtures,
  shell history, or logs; the README documents the same interactive bootstrap
  path for fresh installations.
