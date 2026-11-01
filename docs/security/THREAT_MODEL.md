# ClassVoice threat model

Status: P4-07 review completed 2026-11-01

Owners: application, platform, and security maintainers

Review trigger: before every pilot release and after any auth, storage, model, or network-boundary change

## Scope and security objectives

This review covers the web application, API, worker, PostgreSQL/RLS layer, Redis queue and leases, private object storage, OpenVoice V2/MeloTTS runtime, CI/CD, and operator workflows. The security objectives are:

1. A user can access only resources in a workspace where current membership permits the operation.
2. Voice samples, source text, embeddings, generated audio, credentials, and signed URLs remain private.
3. A generation uses an approved, checksum-pinned model and an active consent record.
4. Mutations are auditable, idempotent where required, and resilient to duplicate or stale workers.
5. Untrusted audio, text, URLs, and webhook targets cannot escape their bounded processing paths.
6. Staging and production fail closed when durable state or abuse controls are unavailable.

## Assets and trust boundaries

| Boundary | Trusted side | Untrusted input | Required controls |
|---|---|---|---|
| Browser to web/API | Authenticated application | Headers, cookies, text, files, route parameters | Secure session handling, schema validation, CSRF-safe auth design, CSP/TLS at ingress |
| API to PostgreSQL | Parameterized server repositories | User/workspace identifiers and query filters | Verified JWT/API key, membership lookup, least privilege, RLS, transactions |
| API to object storage | Server-only storage adapter | Filenames, MIME, sizes, object lifecycle requests | Private buckets, generated keys, quarantine, 600-second signed URLs |
| API to Redis/worker | Authenticated control plane | Job metadata and delivery timing | Durable queue, bounded payloads, leases, retry limits, idempotency |
| Worker to model/audio tools | Isolated worker | Uploaded audio and generation text | Checkpoint pinning, no runtime downloads, FFmpeg limits, process timeout, output bounds |
| API to webhooks | Controlled egress | Tenant-supplied HTTPS URL and remote DNS | HTTPS-only, SSRF validation, re-resolution, egress restrictions, signed payloads |
| CI to dependencies/artifacts | Locked build pipeline | Package registries and repository history | Lockfiles, vulnerability/license/secret gates, minimal permissions, protected branches |
| Operator to hosted services | Authorized operations | Deployment and recovery commands | MFA, least privilege, secret manager, audit logs, tested restore/rollback |

## Threat analysis and disposition

| ID | Threat | Impact | Control/evidence | Disposition |
|---|---|---|---|---|
| TM-01 | Cross-workspace IDOR or role escalation | Critical privacy breach | Auth dependencies resolve membership server-side; RLS replay and HTTP integration tests cover anonymous, cross-workspace, viewer, API-key, revoked-consent, and disabled-workspace paths | Mitigated; retain as release gate |
| TM-02 | Production data/queue state held only in process memory | High integrity and availability loss; multi-instance divergence | `RuntimeSettings` rejects `staging` and `production` while in-memory runtime adapters remain | Contained by fail-closed startup; P4-08 release blocker until SQL/Redis adapters replace local stores |
| TM-03 | Missing distributed request/generation rate limits | High cost/availability abuse | Endpoint-specific request quotas, weighted generation-character quotas, atomic Redis counters, hashed subjects, rate headers, backend readiness, and fail-closed hosted behavior are covered by unit and live Redis tests | Mitigated; hosted profile must select Redis and retain monitoring |
| TM-04 | Malicious or polyglot audio exploits media tools | High worker compromise or resource exhaustion | Exact container-envelope checks, signature rejection, probe/decode timeouts, protocol allowlist, byte/duration caps, synthetic adversarial fixtures | Mitigated |
| TM-05 | Unicode/control-character or oversized prompt abuse | High resource exhaustion or provenance ambiguity | 10,000-code-point boundary, unsafe-control/surrogate rejection, no normalization, bounded logs and hashes | Mitigated |
| TM-06 | SSRF through webhook configuration | High internal-network access | HTTPS validation and server-side URL policy exist; production also requires private-network egress policy and DNS revalidation | Mitigated in application; infrastructure control required before pilot |
| TM-07 | API/JWT/webhook/storage secret disclosure | Critical account or data compromise | Redacted diagnostics/audit metadata, server-only keys, one-time secret UI, repository/history secret scanner, incident rotation runbook | Mitigated; rotate immediately on detection |
| TM-08 | Public or long-lived voice/generation objects | Critical biometric/privacy exposure | Private bucket allowlist, generated keys, authorization checks, 600-second signed URLs, no object keys/URLs in audit events | Mitigated |
| TM-09 | Consent revocation race or unauthorized cloning | Critical safety/privacy harm | Immutable consent evidence, active-consent uniqueness, readiness invariants, automatic voice revocation, generation blocking, moderation reporting | Mitigated; operator abuse review remains required |
| TM-10 | Model/checkpoint substitution or runtime download | High supply-chain and provenance failure | Repository manifest, exact SHA-256 verification, approved license flag, disabled-by-default model, runtime download prohibition | Mitigated |
| TM-11 | Vulnerable dependency causes denial of service | High availability impact | Zod upgraded to 4.6.7; production npm audit and Python `pip-audit` report no known vulnerability; CI repeats gates | Resolved for reviewed lockfile |
| TM-12 | Duplicate/stale worker overwrites output | High integrity failure | Atomic leases, heartbeat/reaping rules, post-inference lease validation, checksum-idempotent output commit, deterministic reliability tests | Mitigated |
| TM-13 | Audit/log channel leaks voice text or credentials | High privacy breach | Allowlisted bounded metadata and explicit redaction of text/audio/embeddings/secrets/URLs/keys | Mitigated; review new event schemas |
| TM-14 | Backup theft, corruption, or untested restore | High confidentiality/availability loss | Encrypted hosted backups required; isolated logical/object restore drill validates schema, data, migration head, and checksums | Mitigated for procedure; hosted PITR proof required before pilot |
| TM-15 | CI token or dependency-chain compromise | High source/release compromise | Read-only CI contents permission, exact runtime versions, lockfiles, no install scripts, vulnerability/license/secret checks | Mitigated; branch protection and artifact signing are deployment prerequisites |

## Residual risk and release decision

- Local Compose deliberately exposes development services and uses local-only credentials. It is not a production topology.
- The full npm development tree has moderate advisories that do not appear in the production dependency closure. They remain tracked and must not be promoted to runtime dependencies without review.
- The local logical restore drill does not prove a hosted provider's point-in-time recovery SLA. P4-08 must record a hosted backup/PITR exercise.
- GPU performance remains a known gap until the approved model meets the reference-hardware gate.
- A pilot release is **not authorized** while TM-02 or TM-03 requires the fail-closed startup guard. Removing the guard without implementing and testing durable SQL/Redis repositories and distributed rate limits is prohibited.

## Review checklist

- [x] Trust boundaries and protected data identified.
- [x] STRIDE-style spoofing, tampering, repudiation, disclosure, denial-of-service, and privilege-escalation paths reviewed.
- [x] Critical/high findings are resolved or fail-closed so they are not exposed in staging/production.
- [x] Dependency, license, model provenance, and secret-history evidence recorded.
- [x] Database and object restore procedure exercised.
- [x] Incident containment and recovery actions documented.
- [x] Distributed request and generation-character rate limits implemented and tested with Redis.
- [ ] Durable production repositories implemented (P4-08 blocker).
- [ ] Hosted PITR and production-network egress controls exercised (P4-08 blocker).
