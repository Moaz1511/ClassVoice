# Pilot rollback runbook

This runbook is provider-neutral until ADR-002 selects the hosted platform. ADR-002 must add exact provider commands without weakening these controls.

## Preconditions

- Record the current and previous release commit, tag, API/web/worker image digests, database migration revision, model manifest digest, and start time.
- Confirm the previous release is compatible with the current database schema. ClassVoice migrations are forward-only during an application rollback unless an independently tested restore is required.
- Assign rollback commander, operator, evidence recorder, and communications owner.
- Do not run `docker compose down -v`, delete a hosted database/bucket, reuse mutable image tags, or expose secrets in terminal transcripts.

## Triggers

Rollback immediately for cross-workspace access, consent bypass, private-object disclosure, signing/checkpoint mismatch, destructive migration behavior, unbounded generation abuse, or sustained critical health failure. The release owner may roll back for SLO regression after preserving evidence.

## Application rollback

1. Stop new generation admission while allowing safe in-flight jobs to finish or be canceled according to the incident decision.
2. Preserve request IDs, audit rows, metrics, deployment events, and image/model digests.
3. Set the API, web, and worker deployment to the previous **immutable image digests**. Keep the current database and object data in place only when backward compatibility was verified.
4. Wait for rollout completion; require live/ready health, database/Redis/storage connectivity, migration compatibility, and worker lease health.
5. Run anonymous/cross-workspace denial, API-key revocation, consent revocation, signed-download, rate-limit, and one consent-confirmed synthetic smoke flow.
6. Re-enable generation admission gradually and monitor auth failures, queue depth, platform failure rate, latency, storage errors, and moderation reports.

## Data restore escalation

If integrity checks fail or an incompatible/destructive migration occurred, stop writes and follow `docs/operations/BACKUP_RESTORE.md`. Restore into new isolated database and bucket targets; never overwrite the only surviving environment. Validate migration head, schema fingerprint, row/checksum evidence, RLS, consent/revocation, and synthetic smoke before switching traffic.

## Local Compose rehearsal

Local rehearsal validates operator order but is not hosted rollback evidence:

```powershell
git fetch --tags
git worktree add ..\classvoice-rollback <previous-release-ref>
Set-Location ..\classvoice-rollback
docker compose config --quiet
docker compose build api web worker
docker compose up -d postgres redis storage api web worker
docker compose ps
curl.exe -fsS http://localhost:8000/health/ready
curl.exe -fsS http://localhost:3000/health/ready
```

Use a separate Compose project/database/ports if the active environment is still running. Never attach a rehearsal to production credentials or volumes. Remove the worktree only after evidence is captured and its absolute path is verified.

## Completion evidence

Record trigger, decision time, operator/approvers, from/to digests, migration/model versions, start/end/elapsed time, health and security results, smoke output hashes, data-integrity result, residual impact, and follow-up owner/due date. A rollback is complete only when monitoring is stable and temporary access/flags are removed.
