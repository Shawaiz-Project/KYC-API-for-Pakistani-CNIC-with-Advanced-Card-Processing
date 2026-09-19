# Deployment, backup, model replacement, and rollback

## Staging

1. Copy `.env.example` and `deployment/staging.env.example` into a secret
   manager-backed `.env`; generate independent Django, identifier-HMAC,
   database, API, and Fernet secrets.
2. Provision the documented model files read-only and record license,
   acquisition URL/date, byte size, SHA-256, preprocessing contract, and
   evaluation report. Run `python main.py model_manifest` before replacement.
3. `docker compose build`, then `docker compose run --rm backend python manage.py migrate --plan`.
4. Back up PostgreSQL and the private-object volume. Run migrations with
   `docker compose run --rm backend python manage.py migrate`.
5. `docker compose up -d`, then require live/ready, worker, frontend, private
   media authorization, webhook, and end-to-end path checks before promotion.
6. Public DNS/TLS exposure is a separate approval; Compose binds the frontend
   only to localhost by default.

## PostgreSQL backup/restore demonstration

```bash
docker compose exec -T postgres pg_dump -Fc -U shanakht shanakht > private-backup.dump
docker compose exec -T postgres createdb -U shanakht shanakht_restore_test
docker compose exec -T postgres pg_restore -U shanakht -d shanakht_restore_test --clean --if-exists < private-backup.dump
docker compose exec -T postgres psql -U shanakht -d shanakht_restore_test -c "select count(*) from detector_kycapplication;"
docker compose exec -T postgres dropdb -U shanakht shanakht_restore_test
```

Store backups encrypted and test object-store restore against a separate bucket
or volume. The acceptance workstation has no Docker executable, so these steps
are documented but were not executed in this run.

## Model replacement

- Stage new weights under a new immutable path; never overwrite a live file.
- Verify the recorded SHA-256/license/input-output contract and run readiness,
  calibration, final evaluation, and regression comparison.
- Update path/checksum/model version together, restart workers so each loads the
  model once, and confirm metrics are separated by model version.
- Retain the previous immutable assets/config for rollback. Do not mix detector
  and policy versions in one decision history.

## Rollback

- Application: deploy the previous image digest and configuration; do not run
  reverse migrations until compatibility has been assessed.
- Database: prefer a forward corrective migration. If restoration is required,
  stop writers/workers, restore the verified snapshot and matching private
  objects to an isolated environment, validate counts/integrity, then switch.
- Models: restore previous paths/checksums and restart every worker.
- Webhooks: preserve event/delivery IDs; replay only explicitly selected failed
  events so consumers can retain idempotency.

## Operations

- Schedule `cleanup_application_data` at least as often as the shortest
  retention window; use `--dry-run` first.
- Track `/api/v2/metrics`, queue depth, job failures, detector unavailability,
  recapture rate, reviewer corrections, webhook failures, p95 latency, and RSS.
  Never use CNIC, names, image hashes, application references, or biometric
  values as labels.
- Celery 5.6 does not support native Windows workers; use the Linux container
  profile for staging/production.
