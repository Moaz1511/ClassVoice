# Security and privacy incident response runbook

Owner: incident commander assigned by the project owner

Review cadence: before each pilot release and after every incident or drill

## Severity and activation

| Severity | Examples | Initial response target |
|---|---|---|
| SEV-1 | Confirmed voice/audio/text disclosure, signing-key compromise, cross-workspace access, malicious model artifact, destructive data loss | Acknowledge immediately; begin containment within 15 minutes |
| SEV-2 | Suspected credential exposure, sustained generation abuse, SSRF attempt with possible reachability, material service degradation | Acknowledge within 30 minutes; contain within 60 minutes |
| SEV-3 | Blocked attack, low-volume policy misuse, non-sensitive outage, dependency advisory without demonstrated exposure | Triage within one business day |

Anyone may declare an incident. Create a private incident record with a UTC timeline, assign an incident commander, operations lead, communications lead, and evidence recorder. Do not paste voice samples, prompt text, tokens, signed URLs, or personal data into chat/tickets.

## First 30 minutes

1. Preserve relevant request IDs, bounded audit rows, deployment/version identifiers, model manifest digest, and infrastructure logs. Record hashes for exported evidence and restrict access.
2. Determine affected workspaces, resource types, time window, model/checkpoint, and whether confidentiality, integrity, consent, or availability is involved.
3. Prefer reversible containment: disable generation, revoke affected API keys/sessions/webhooks, disable the model manifest entry, isolate workers, or block egress. Do not delete evidence.
4. If a secret may have been disclosed, treat it as compromised; never wait for proof of use.
5. Notify the project owner and privacy/legal contact placeholder. They decide regulatory/user notification requirements and timing.

## Scenario playbooks

### Credential or signing-key exposure

1. Revoke/rotate in this order: affected user/API key, webhook signing secret, storage credentials, worker callback secret, service-role credential, JWT signing key.
2. For JWT-key rotation, accept the new key, invalidate prior sessions, then remove the old key after the shortest safe overlap. Record key IDs, never key values.
3. Search redacted logs by request ID/key prefix and review access from the earliest possible exposure time.
4. Redeploy from a known commit and validate auth, workspace isolation, signed-URL expiry, and revocation behavior.

### Cross-workspace or private-object disclosure

1. Disable the affected route or service and generation/download capabilities.
2. Revoke active signed URLs where the provider permits it; otherwise rotate the object-storage signing credential and enforce private bucket policy.
3. Capture RLS policies, membership/audit records, and object access logs. Run the cross-workspace security suite before reopening.
4. Identify every affected workspace/resource and preserve deletion/consent state for notification review.

### Unauthorized voice cloning or consent abuse

1. Revoke the voice/consent and stop queued/in-flight jobs; disable downloadable outputs.
2. Preserve immutable consent, audit, moderation, model, and output-checksum evidence without copying raw audio into the incident record.
3. Suspend the actor/API key where policy permits and route the report to moderator review.
4. Reopen only after authorization, consent, and deletion controls have been independently verified.

### SSRF, worker, or model compromise

1. Isolate the affected API/worker workload and block outbound network access except allowlisted dependencies.
2. Disable the implicated webhook endpoint or model manifest entry.
3. Preserve container/image digest, manifest, checkpoint SHA-256, DNS resolution, destination IPs, and process logs.
4. Rebuild from pinned dependencies and approved model artifacts; do not reuse a potentially modified cache or checkpoint.

### Destructive data loss or ransomware

1. Stop writes and protect backup retention; do not attach backup credentials to the affected runtime.
2. Establish a clean recovery environment and follow `docs/operations/BACKUP_RESTORE.md`.
3. Restore to a new database/bucket, validate migration head, counts, schema fingerprint, sentinel/checksums, RLS, and application health.
4. Switch traffic only with incident-commander approval and retain the compromised environment for evidence.

## Recovery and closure

Before service restoration, two people review the containment change, dependency/model provenance, secret rotation, data integrity, workspace isolation, and monitoring. Run focused security tests plus a consented synthetic smoke flow; never use a student's real voice for an incident drill.

Within five business days, publish an internal blameless postmortem containing impact, exact timeline, root and contributing causes, control failures, detection gaps, recovery evidence, and owned/due-dated actions. Update this runbook, the threat model, and tests. Close the incident only when temporary credentials/rules are removed and all evidence is retained according to policy.

## Required operator placeholders before pilot

- Incident commander/on-call: **UNASSIGNED**
- Privacy/legal contact: **UNASSIGNED**
- Hosting/provider escalation: **UNASSIGNED**
- User communication owner and approved template: **UNASSIGNED**

These unassigned contacts are P4-08 pilot blockers.
