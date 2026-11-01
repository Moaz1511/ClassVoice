# Backup and restore policy and verification

Last local drill: 2026-11-01

Scope: PostgreSQL schema/data and private object storage

## Production policy

- Use provider-managed encrypted PostgreSQL backups with point-in-time recovery. Target RPO is 15 minutes and target RTO is 4 hours for the pilot; provider configuration and a timed hosted drill must prove these targets before release.
- Enable versioning/retention for private object storage where available. Keep backup credentials in a separate operator role; application and worker credentials must not delete backup history.
- Encrypt backups in transit and at rest, restrict restore access with MFA/least privilege, and audit exports/restores.
- Keep database and object snapshots from a consistent recovery window. Retention and deletion must honor consent, privacy, and legal requirements rather than retaining biometric/voice data indefinitely.
- A backup is not accepted until a restore into an isolated environment verifies migrations, schema, data, RLS/security tests, and object checksums.

## Reproducible local drill

Run from the repository root with the Compose PostgreSQL and LocalStack services healthy:

```powershell
python scripts/verify_backup_restore.py
```

The script uses fixed, clearly named disposable databases/buckets, reads but never modifies the normal `classvoice` database, creates a logical database backup, copies a synthetic object through the backup bucket, restores into a clean database/bucket, and removes every test resource in `finally` cleanup. It refuses arbitrary database or bucket targets.

The 2026-11-01 drill passed in 110.483 seconds with:

- migration head `0009_audit_fk_maintenance`;
- 21 public tables;
- matching database schema fingerprint `655c014f97f1c95522b1040acd4e7628`;
- matching database sentinel SHA-256 `eb9a5865fd08069b2af0d39bfe4b9c0c043d44a41f6e8a4c6932b660aeefb4d9`;
- matching object SHA-256 `501462170d9c6a452ec1b27a8db6c400dc8c009418b10c4a2669cd43d179190e`;
- one expected synthetic object restored;
- logical backup SHA-256 `4d3bd49b58d77daa80e96d4caa697c5e872ebf9c2090ad26127c140a0ea58e3b`.

These values are evidence for this synthetic local run, not production backup identifiers or an RTO guarantee.

## Hosted recovery procedure

1. Declare an incident/change window, stop or drain writes, and record the desired recovery timestamp.
2. Provision a new isolated database and private bucket; never restore over the only surviving environment.
3. Restore the provider snapshot/PITR database and the corresponding object version/snapshot.
4. Verify migration head, expected table/index/policy inventory, row-count ranges, referential integrity, and application-specific sentinel/checksums.
5. Run migration replay, RLS/cross-workspace tests, consent/revocation tests, signed-URL tests, and an approved synthetic smoke generation.
6. Rotate credentials used during recovery, deploy the known application/model version, and switch traffic using the documented rollback window.
7. Monitor auth failures, queue depth, generation errors, storage access, and audit continuity. Retain the old environment read-only until the incident commander approves disposal.

## Evidence required for P4-08

- Provider backup/PITR settings and retention screenshot/export without secrets.
- Timed hosted restore record with achieved RPO/RTO.
- Database and object integrity results plus RLS/security-suite result.
- Operator names/approvals and rollback decision point.
