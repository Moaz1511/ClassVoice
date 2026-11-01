# Pilot release checklist

Status: blocked preflight; no release tag exists

Candidate naming: `v0.1.0-pilot.N`

## Hard stop conditions

Do not deploy or tag a pilot while any of these conditions is true:

- staging/production cannot pass `APISettings.validate()`;
- a tenant resource, API key, audit event, queue, lease, or output record is process-local;
- the hosted profile does not use Redis request and character quotas;
- the approved model manifest entry is disabled or its checkpoint SHA-256 differs;
- the 10,000-character GPU gap lacks an accepted limit/segmentation decision;
- hosting, private networking, egress, secret storage, backup/PITR, and log retention are undecided;
- incident/privacy/provider/communication owners are unassigned;
- CI, hosted restore, consented synthetic smoke, metrics, or rollback rehearsal has not passed.

The executable guard is:

```powershell
python scripts/pilot_release_preflight.py `
  --candidate v0.1.0-pilot.1 `
  --evidence private/pilot-release/evidence.json
```

It must exit `0` with `"status": "pass"`. Never override a failed check or edit the script to fit an incomplete release.

## 1. Prepare immutable release inputs

1. Merge the reviewed commit to the protected release branch.
2. Confirm the GitHub Actions run for that exact SHA completed successfully.
3. Build API, web, and worker images from the SHA; record registry image digests, not mutable tags.
4. Verify the OpenVoice checkpoint against `infra/model-registry/manifest.json` and ADR-001 before enabling the entry through a reviewed manifest change.
5. Copy `infra/release/pilot-evidence.example.json` to ignored `private/pilot-release/evidence.json`; replace every placeholder with non-secret evidence.
6. Store credentials only in the provider secret manager. Do not put tokens, URLs with signatures, voice IDs, or raw audio/text in evidence.

## 2. Deploy an isolated staging candidate

1. Provision managed PostgreSQL with encrypted PITR, private object storage, persistent Redis, API/web containers, and one isolated GPU worker according to the accepted hosting ADR.
2. Restrict inbound traffic to HTTPS ingress and the signed/mTLS worker callback. Restrict worker/API egress to documented destinations.
3. Run Alembic `upgrade head` as a one-shot migration job before application traffic. Record the migration revision.
4. Deploy immutable image digests with `APP_ENV=staging`, Supabase authentication, TLS Redis (`rediss://`) rate limiting, private storage, and the approved model artifact mounted read-only.
5. Require `/health/live` and `/health/ready` to pass. Readiness must prove configuration and Redis protection; durable database/storage checks must be present when their adapters are installed.

## 3. Verify safety and behavior

1. Run cross-workspace/RLS, API-key revocation, consent revocation, private signed-download, and deletion tests against staging using synthetic tenants.
2. Confirm endpoint-specific `RateLimit-*` headers and a stable `429 RATE_LIMITED` response; stop Redis briefly in an isolated drill and confirm hosted requests fail closed with `503 RATE_LIMIT_UNAVAILABLE`.
3. Prepare a synthetic/reference voice with a documented active consent receipt. Then run:

```powershell
$env:CLASSVOICE_PILOT_BEARER_TOKEN = "<short-lived operator token>"
$env:CLASSVOICE_PILOT_API_URL = "https://api.staging.example"
$env:CLASSVOICE_PILOT_WORKSPACE_ID = "<synthetic workspace UUID>"
$env:CLASSVOICE_PILOT_VOICE_PROFILE_ID = "<consented voice UUID>"
$env:CLASSVOICE_PILOT_MODEL_KEY = "openvoice-v2"
$env:CLASSVOICE_PILOT_MODEL_VERSION = "2.0.0"
$env:CLASSVOICE_PILOT_CHECKPOINT_SHA256 = "<approved SHA-256>"
python scripts/pilot_smoke.py --confirm-consent
Remove-Item Env:CLASSVOICE_PILOT_BEARER_TOKEN
```

The output is safe JSON containing hashes and timings only. It must report `pass`; store it in the private release evidence system.

## 4. Record the pilot baseline

Measure at least 200 authenticated reads, 100 authorization-checked signed URLs, the accepted maximum generation length, queue depth/time, generation/inference latency, platform failure rate, storage consumption, and rate-limit rejections. Compare them with `docs/01_PRD.md` and record pass/known gap in `docs/performance/P4-08_Baseline.md`.

Required thresholds are API-read P95 below 400 ms, platform generation failures at or below 5%, signed URLs exactly 600 seconds, active consent for every Ready voice, and no critical/high unresolved security issue. The accepted long-text decision controls the generation workload; do not claim the unmet P4-06 10,000-character target.

## 5. Rehearse rollback and approve

Follow `docs/operations/ROLLBACK.md` in staging using the exact candidate and previous immutable image digests. Record elapsed time, health/security/smoke results, data integrity, and the rollback decision point. Complete the hosted backup/PITR restore evidence in `docs/operations/BACKUP_RESTORE.md`.

The release owner, security reviewer, and privacy reviewer must review the same commit/evidence and fill the approval fields. Re-run the executable preflight.

## 6. Create the tag only after a passing preflight

```powershell
git status --short
git rev-parse HEAD
python scripts/pilot_release_preflight.py --candidate v0.1.0-pilot.1
git tag -a v0.1.0-pilot.1 -m "ClassVoice pilot 0.1.0-1"
git push origin v0.1.0-pilot.1
git rev-list -n 1 v0.1.0-pilot.1
```

The working tree must be clean and the local/remote tag must resolve to the evidence commit. Publish release notes containing model/checkpoint provenance, migrations, metrics/known gaps, security/backup approvals, and the rollback reference—never credentials or private asset identifiers.
