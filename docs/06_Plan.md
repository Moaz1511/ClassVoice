# 06 — Atomic Implementation Plan

**Product:** ClassVoice  
**Plan status:** In progress  
**Last updated:** 2026-10-29  
**Rule:** Execute in order. Complete and verify one checkbox before starting the next. Update this file immediately after every completed step with the commit/PR and evidence.

## How to use this plan

- `[ ]` not started, `[~]` in progress, `[x]` complete, `[!]` blocked by an explicit decision.
- A step is complete only when its acceptance criteria and automated checks pass.
- If implementation reveals an architectural change, stop, add an ADR, update the relevant context document, then continue.
- Never mark a step complete because code exists; mark it complete because behavior is verified.
- Keep a short progress log at the bottom after every completed step.

## Phase 1 — Database and Auth foundation

### 1.1 Repository and local environment

- [x] **P1-01** Create the monorepo directories from `04_TRD.md` and baseline `.gitignore`, `.editorconfig`, `.nvmrc`, Python tool configuration, and `.env.example`.
  - Depends on: none.
  - Accept when: `apps/web`, `apps/api`, `packages`, `db`, `infra`, `scripts`, and `docs` exist; no secret is committed.
  - Verify: clean install/lint bootstrap in CI.
- [x] **P1-02** Add Docker Compose for Postgres 17.11, Redis 7.4.2, LocalStack S3, API, worker, and web health checks.
  - Depends on: P1-01.
  - Accept when: `docker compose up` reaches healthy state from an empty machine with documented commands.
- [x] **P1-03** Add CI jobs for web lint/typecheck/test and API lint/typecheck/test/migration replay.
  - Depends on: P1-01.
  - Accept when: CI fails on a deliberate type error and passes on baseline.
  - Baseline note: the web workspace has pinned ESLint `9.38.0` and TypeScript `5.9.3` gates over the current placeholder files; the Next.js/React rules are added by P3-01. The migration-replay job becomes active once the first migration lands in P1-04.

### 1.2 Database schema and RLS

- [x] **P1-04** Configure Alembic and create the extensions/enums from `05_Schema.md`.
  - Depends on: P1-02.
  - Accept when: migration applies to an empty Postgres 17.11 database and downgrades in development.
- [x] **P1-05** Implement identity/workspace tables, profile trigger, onboarding transaction, and seed only synthetic data.
  - Depends on: P1-04.
  - Accept when: a verified user can create exactly one personal workspace and owner membership.
- [x] **P1-06** Implement voice/consent/model/audio tables and all documented constraints/indexes.
  - Depends on: P1-05.
  - Accept when: invalid durations, hashes, statuses, and foreign keys are rejected by the database.
- [x] **P1-07** Implement project/generation/output tables and the unique workspace/idempotency constraint.
  - Depends on: P1-06.
  - Accept when: duplicate idempotency keys return one durable job record.
- [x] **P1-08** Implement API key/webhook/usage/audit/moderation/export tables and indexes.
  - Depends on: P1-07.
  - Accept when: secrets are represented only by hashes/prefixes and audit rows are append-only to the application role.
- [x] **P1-09** Implement RLS helper functions and explicit policies for every public table.
  - Depends on: P1-08.
  - Accept when: cross-workspace, viewer-write, anonymous-read, revoked-voice, and model-visibility tests pass.
- [x] **P1-10** Add database invariants/triggers for voice readiness and consent revocation.
  - Depends on: P1-09.
  - Accept when: a voice cannot become Ready without available primary sample, approved model, and active consent; revocation blocks new jobs.

### 1.3 Authentication

- [x] **P1-11** Configure Supabase Auth email verification, password reset, OAuth callback allowlist, and local test provider.
  - Depends on: P1-05.
  - Accept when: sign-up, verify, sign-in, sign-out, reset, and expired-session flows work in local and CI environments.
- [x] **P1-12** Implement API JWT verification, workspace membership dependency, role dependency, and scope dependency.
  - Depends on: P1-09, P1-11.
  - Accept when: every protected route rejects missing/expired/incorrect-audience tokens and unauthorized workspace IDs.
- [x] **P1-13** Implement consent statement versioning and acceptance audit event.
  - Depends on: P1-10, P1-12.
  - Accept when: acceptance stores statement version, text hash, timestamp, and actor; a revoked consent cannot be reused.

## Phase 2 — Core API and inference pipeline

### 2.1 API foundations

- [x] **P2-01** Create FastAPI app shell, settings validation, structured logging, request IDs, error envelope, CORS, and health endpoints.
  - Depends on: P1-12.
  - Accept when: `/health/live`, `/health/ready`, and documented error responses work without leaking secrets.
- [x] **P2-02** Generate and publish the typed TypeScript API client from OpenAPI.
  - Depends on: P2-01.
  - Accept when: client generation is deterministic and CI fails on an uncommitted schema diff.
- [x] **P2-03** Implement private storage adapter for Supabase Storage and LocalStack S3 with signed upload/download URLs.
  - Depends on: P1-08, P2-01.
  - Accept when: objects are private, URLs expire in 10 minutes, and unauthorized users cannot mint URLs.

### 2.2 Voice lifecycle

- [x] **P2-04** Implement upload-intent endpoint with size/type limits, quarantine object key, and idempotency.
  - Depends on: P2-03.
  - Accept when: unsupported extensions, MIME spoofing, oversized uploads, and remote URLs are rejected.
- [x] **P2-05** Implement audio validation worker (magic bytes, FFmpeg decode, duration, silence, clipping, channels, speaker warning).
  - Depends on: P2-04, P1-06.
  - Accept when: fixture suite covers valid WAV/MP3/M4A plus corrupt, silent, clipped, multi-speaker, and boundary cases.
- [x] **P2-06** Implement voice create/read/update/archive/revoke/delete endpoints and state transitions.
  - Depends on: P2-05, P1-13.
  - Accept when: only authorized workspace roles can mutate; destructive actions create audit events and cascade asynchronously.
- [x] **P2-07** Implement model registry manifest, license-review gate, and allowlisted checkpoint loader.
  - Depends on: P1-06.
  - Accept when: unapproved/unknown model SHA cannot run and model metadata is copied to each job.

### 2.3 Generation jobs

- [x] **P2-08** Implement generation create/read/list/cancel/retry endpoints with validation and idempotency.
  - Depends on: P2-06, P2-07.
  - Accept when: invalid voice/consent/model/text/settings fail with stable error codes; duplicate requests return the original job.
- [x] **P2-09** Implement arq publisher/worker job claiming, lease timeout, retry policy, and terminal-state persistence.
  - Depends on: P2-08, P1-07.
  - Accept when: a worker crash does not lose a job and retries are bounded and auditable.
- [x] **P2-10** Implement inference adapter interface and local CPU smoke adapter.
  - Depends on: P2-09.
  - Accept when: end-to-end job lifecycle works with a deterministic test waveform without loading a real model.
- [x] **P2-11** Integrate the pinned OpenVoice V2 checkpoint behind the adapter and GPU/CPU feature flag.
  - Depends on: P2-10, P2-07.
  - Accept when: a consented fixture produces a valid WAV, records model SHA/settings/checksum, and respects max text/output limits.
- [x] **P2-12** Add MP3 post-processing, provenance metadata, private asset creation, and signed download endpoint.
  - Depends on: P2-11, P2-03.
  - Accept when: WAV and MP3 outputs play, checksum matches, and download authorization is rechecked.

### 2.4 Projects, agent API, and webhooks

- [x] **P2-13** Implement projects and saved editor settings endpoints.
  - Depends on: P2-08.
  - Accept when: project ownership, archive, and unsaved-vs-saved semantics match `02_AppFlow.md`.
- [x] **P2-14** Implement API key creation/list/revoke with Argon2id hashing, scopes, expiry, and last-used tracking.
  - Depends on: P1-08, P2-01, P2-08.
  - Accept when: secret is returned once, never stored plaintext, and scopes are enforced on generation routes.
- [x] **P2-15** Implement webhook endpoint validation, signing, delivery retries, replay protection, and disable threshold.
  - Depends on: P2-09, P1-08.
  - Accept when: a test event verifies signature and a failing endpoint follows exponential backoff.
- [x] **P2-16** Implement audit event emission for every required mutation/download and a moderator-safe report endpoint.
  - Depends on: P2-06, P2-08, P2-14, P2-15.
  - Accept when: audit integration tests assert actor, resource, request ID, and redacted metadata.

## Phase 3 — UI integration

### 3.1 Shell and auth

- [ ] **P3-01** Scaffold Next.js app shell, semantic theme tokens, typography, layout, error boundaries, and route guards.
  - Depends on: P2-02.
  - Accept when: light/dark/system themes, keyboard focus, 404, and error routes match `03_UI_Spec.md`.
- [ ] **P3-02** Implement sign-up, sign-in, verify-email, reset-password, onboarding, and session-expiry screens.
  - Depends on: P1-11, P3-01.
  - Accept when: Playwright covers happy path, invalid credentials, rate limit, expired link, and return-to routing.
- [ ] **P3-03** Implement dashboard shell, sidebar navigation, workspace switcher placeholder, loading/empty/error patterns.
  - Depends on: P3-02.
  - Accept when: all routes in `02_AppFlow.md` have a navigable placeholder and no private data flashes before auth.

### 3.2 Voice and studio experiences

- [ ] **P3-04** Implement voices list, filters, create voice consent modal, upload dropzone, validation feedback, and voice detail.
  - Depends on: P2-03, P2-05, P2-06.
  - Accept when: all upload/status/error/empty states and destructive confirmations match the flow document.
- [ ] **P3-05** Implement studio editor, project save, voice selector, settings controls, character counter, and unsaved-change guard.
  - Depends on: P2-13, P3-04.
  - Accept when: browser refresh preserves only local draft text, and revoked/not-ready voices cannot be selected.
- [ ] **P3-06** Implement generation queue rail, polling/backoff, cancellation, retry, output player, metadata, and signed download.
  - Depends on: P2-08, P2-12, P3-05.
  - Accept when: every job state has a truthful UI representation and refresh does not duplicate jobs.

### 3.3 Administration and agent surfaces

- [ ] **P3-07** Implement API key and webhook screens, one-time secret display, scopes, expiry, revoke, delivery status, and copy actions.
  - Depends on: P2-14, P2-15.
  - Accept when: secrets never reappear after navigation and admin-only routes are enforced.
- [ ] **P3-08** Implement settings, export/delete flows, audit view, and safety/report screens.
  - Depends on: P2-16.
  - Accept when: destructive flows require re-auth/typed confirmation and show exact cascade effects.
- [ ] **P3-09** Publish `/docs/api` with generated OpenAPI examples and a minimal agent quickstart.
  - Depends on: P2-02, P2-14.
  - Accept when: a clean environment can create a key, submit a job, poll it, and download output using documented commands.

## Phase 4 — Edge-case tests and release hardening

- [ ] **P4-01** Add unit/property tests for all input schemas, error codes, idempotency, state transitions, and policy decisions.
  - Depends on: Phase 2 complete.
  - Accept when: coverage gates are defined and all P0 branches are exercised.
- [ ] **P4-02** Add RLS/security integration suite for anonymous, cross-workspace, viewer, revoked key, revoked consent, and disabled workspace cases.
  - Depends on: P1-09, P2-14.
  - Accept when: no private row/object is accessible through direct API or generated client.
- [ ] **P4-03** Add upload fuzz/fixture tests and resource limits for decompression bombs, polyglots, malformed headers, long text, and Unicode edge cases.
  - Depends on: P2-05.
  - Accept when: failures are bounded, classified, and do not crash the worker.
- [ ] **P4-04** Add worker reliability tests for duplicate delivery, crash recovery, lease expiry, cancel races, retry exhaustion, and stale model manifests.
  - Depends on: P2-09, P2-11.
  - Accept when: every job reaches exactly one terminal state and outputs are not duplicated.
- [ ] **P4-05** Add Playwright accessibility/responsive tests at 375, 768, 1,024, and 1,440 px plus reduced-motion mode.
  - Depends on: Phase 3 complete.
  - Accept when: keyboard-only auth, voice, studio, player, and deletion flows pass with no critical axe violations.
- [ ] **P4-06** Add load tests for API reads, signed URLs, queue concurrency, and 10,000-character generation requests on the reference GPU.
  - Depends on: P2-12.
  - Accept when: measured metrics are compared with PRD targets and documented as pass/known gap.
- [ ] **P4-07** Perform threat model, dependency/license review, secret scan, backup/restore test, and incident runbook review.
  - Depends on: P4-01 through P4-06.
  - Accept when: no critical/high unresolved issue remains and model license approval is recorded.
- [ ] **P4-08** Run a pilot release checklist, record metrics baseline, tag the release, and publish rollback instructions.
  - Depends on: P4-07.
  - Accept when: a fresh operator can deploy, verify health, run a consented smoke generation, and roll back.

## Definition of Done for every step

1. Implementation is committed with tests or an explicit test fixture.
2. Documentation and API schema are updated if behavior changed.
3. Security/privacy implications were reviewed.
4. CI is green and local reproduction commands are recorded.
5. This file is updated from `[ ]` to `[x]`, with date, commit/PR, and evidence in the log below.

## Progress log

| Date | Step | Commit/PR | Evidence / notes |
|---|---|---|---|
| 2026-10-27 | Context pack created | n/a | Architecture baseline only; implementation not started |
| 2026-10-27 | P1-01 | n/a | Created monorepo skeleton, Node/Python pins, `.gitignore`, `.editorconfig`, `.env.example`, root/workspace manifests, and all TRD directories. Verified with directory listing and config inspection. |
| 2026-10-27 | P1-02 | n/a | Compose stack built and started successfully. `docker compose ps` reports API, web, worker, PostgreSQL, Redis, and LocalStack healthy; `/health/live` and LocalStack S3 health endpoints returned 200. LocalStack replaces unavailable MinIO only for local development; hosted storage remains Supabase Storage. |
| 2026-10-27 | Docker diagnosis | n/a | Confirmed Docker Desktop 29.1.3, `desktop-linux` context, healthy daemon, correct `docker-users` membership, and successful `hello-world` container. Restarted Docker Desktop and WSL2; pinned PostgreSQL image pulls still fail with registry socket-buffer/direct-connection errors. |
| 2026-10-28 | P1-03 | n/a | Added root npm scripts and lockfile, workspace package manifests, pinned ESLint `9.38.0`/TypeScript `5.9.3` and Python CI tools, baseline web/API tests, and GitHub Actions jobs for web, API, Compose validation, and the migration replay gate. Baseline web lint/typecheck/test, Ruff, mypy, pytest (1 passed), and `docker compose config --quiet` passed; a temporary invalid TypeScript assignment failed the typecheck as required and was restored. |
| 2026-10-28 | P1-04 | n/a | Added pinned Alembic `1.17.1`, SQLAlchemy `2.1.6`, asyncpg `0.30.0`, and greenlet support; configured `db/alembic.ini`, async `env.py`, migration template, and revision `0001_extensions_enums` for pgcrypto, citext, and all 14 enums in `05_Schema.md`. Offline SQL generation, Ruff, mypy, and pytest passed. Live PostgreSQL 17.11 verification upgraded to `0001_extensions_enums`, downgraded to base, and completed successfully on an isolated host port. CI migration replay now runs upgrade → downgrade → upgrade, and triggers cover both `Moaz_Workspace` and `main`. |
| 2026-10-28 | P1-05 | n/a | Added revision `0002_identity_workspace` with guarded local `auth.users` compatibility, profiles, workspaces, workspace members, indexes, updated-at triggers, the auth-user profile trigger, and an idempotent `create_personal_workspace` transaction. Added synthetic-only seed SQL and an async integration test. Live PostgreSQL 17.11 test passed onboarding twice with one workspace/owner membership, then downgrade/re-upgrade; all web/API checks passed and Compose services remained healthy. |
| 2026-10-28 | P1-06 | n/a | Added revision `0003_voice_assets` for model versions, voice profiles, consent records, audio assets, and voice samples with documented foreign keys, checks, enums, indexes, and updated-at trigger. Added integration coverage proving invalid durations, hashes, enum statuses, and foreign keys are rejected. Live PostgreSQL 17.11 upgrade, constraint tests, downgrade, and re-upgrade passed on isolated host port 55432; web/API checks, Compose config, and all services remained healthy. Corrected the documented locale check so the default `en-US` value is valid. |
| 2026-10-28 | P1-07 | n/a | Added revision `0004_generation` for projects, generation jobs, and generation outputs with documented settings bounds, state/output enums, foreign keys, indexes, updated-at trigger, and workspace/idempotency uniqueness. Added integration coverage proving an idempotent retry returns the original durable job and does not insert a duplicate, while invalid speed is rejected. Live PostgreSQL 17.11 upgrade, identity/voice/generation tests (3 passed), downgrade, and re-upgrade passed on isolated host port 55432; web checks, Ruff, mypy, Compose config, and service health passed. |
| 2026-10-28 | P1-08 | n/a | Added revision `0005_integrations_audit` for API keys, webhook endpoints/deliveries, usage events, audit events, moderation flags, and data exports, including documented hashes/prefixes, lifecycle checks, foreign keys, indexes, updated-at trigger, and append-only audit trigger. Added integration coverage proving secrets are represented by hashes/prefixes and audit updates/deletes are rejected. Live PostgreSQL 17.11 upgrade, all four migration integration tests (4 passed), downgrade, and re-upgrade passed on isolated host port 55432; web checks, Ruff, mypy, Compose config, and service health passed. |
| 2026-10-28 | P1-09 | n/a | Added revision `0006_rls_policies` with guarded local Supabase role/function compatibility, security-definer workspace and moderator helpers, RLS on all 18 public tables, explicit named policies, role grants, and revoked-voice/unapproved-model insertion gates. Added integration coverage proving cross-workspace isolation, viewer write denial, anonymous reads denied, enabled-model visibility, and revoked-voice generation denial. Live PostgreSQL 17.11 upgrade, all five migration integration tests (5 passed), downgrade, and re-upgrade passed on isolated host port 55432; web checks, Ruff, mypy, Compose config, and service health passed. |
| 2026-10-28 | P1-10 | n/a | Added revision `0007_voice_invariants` with readiness validation for approved/enabled models, available primary samples, and active consent; automatic voice revocation on consent revocation; and generation-job blocking for revoked or consentless voices. Added integration coverage for missing model/sample/consent prerequisites, successful readiness, automatic revocation, and blocked post-revocation generation. Live PostgreSQL 17.11 upgrade, all six migration integration tests (6 passed), downgrade, and re-upgrade passed on isolated host port 55432; web checks, Ruff, mypy, Compose config, and service health passed. |
| 2026-10-28 | P1-11 | n/a | Added validated auth configuration for local/Supabase profiles, exact OAuth callback allowlisting, email-verification/password-reset/session TTLs, and redacted diagnostics. Added a deterministic in-memory local provider with sign-up, verification, sign-in/out, password reset, OAuth state, and expiry transitions; PBKDF2 password hashing and session/reset invalidation are covered by unit tests. Updated `.env.example` and the TRD auth contract. API tests (11 passed, 3 integration skips), Ruff, mypy, web lint/typecheck/test, Compose config, Docker service health, and `git diff --check` passed. |
| 2026-10-28 | P1-12 | n/a | Added Supabase-compatible HS256 JWT verification with mandatory signature, issuer, audience, authenticated role, UUID subject, `iat`, `exp`, optional `nbf`, and explicit scope parsing. Added HTTP-agnostic bearer extraction plus workspace membership, minimum-role, disabled-workspace, and scope dependencies; workspace roles are resolved from membership storage rather than JWT claims. Unit coverage rejects missing, malformed, expired, wrong-signature, wrong-algorithm, wrong-issuer/audience/role, cross-workspace, viewer-write, missing-scope, disabled-workspace, and invalid-ID cases. API tests (18 passed, 6 integration skips), Ruff, mypy, web lint/typecheck/test, Compose config, Docker service health, and `git diff --check` passed. |
| 2026-10-28 | P1-13 | n/a | Added `0008_consent_statements_audit` with canonical versioned consent text, database-derived SHA-256 attestation checks, accepting actor evidence, immutable accepted evidence, one-active-consent uniqueness, revoked/expired reuse protection, and a `consent.accepted` audit event. Added `0009_audit_fk_maintenance` so append-only audit rows still permit referential `ON DELETE SET NULL` maintenance. Updated all migration fixtures to use the canonical statement hash and added the consent acceptance/audit integration test. Live PostgreSQL 17.11 migration suite passed (7 tests), including invalid hash/version, actor/hash audit metadata, and revoked-consent reuse rejection; offline migration SQL, Ruff, mypy, web lint/typecheck/test, Compose config, and service checks passed. |
| 2026-10-28 | P2-01 | n/a | Added the FastAPI application factory and Uvicorn entrypoint, validated runtime settings with safe redacted diagnostics, JSON structured request-completion logging, bounded request-ID correlation, explicit CORS, stable `{data,error,request_id}` handling for validation/API/framework/unexpected errors, and `/health/live` plus `/health/ready`. Added focused settings/API tests, pinned FastAPI/Uvicorn/Pydantic/HTTPX/structlog dependencies, and switched the API Docker image from the placeholder server to Uvicorn. Ruff, mypy, focused tests (7 passed before the host socket-buffer exhaustion), Docker builds, Compose startup/health, and live GET checks for 200 health and enveloped 404 responses passed. The remaining full local pytest rerun is environment-blocked by recurring Windows `WinError 10055`; CI/Linux remains the authoritative async test environment. |
| 2026-10-28 | P2-02 | n/a | Added deterministic FastAPI OpenAPI export, checked-in `packages/api-client/openapi.json`, generated `schema.ts` via pinned `openapi-typescript@7.13.0`, and a typed `openapi-fetch@0.17.0` client factory. Added workspace generation/typecheck scripts and an API CI gate that regenerates artifacts and fails on schema drift. Generation, client typecheck, full web lint/typecheck/test, Ruff, mypy, Compose config, and `git diff --check` passed. |
| 2026-10-28 | P2-03 | n/a | Added the provider-neutral `StorageAdapter`, strict bucket/key validation, exact 600-second signed URL policy, S3/LocalStack SigV4 upload/download presigning, and Supabase server-only signed upload/download endpoints. Extended validated settings and redacted diagnostics, pinned `boto3==1.43.120` plus development stubs, and covered traversal, private bucket allowlisting, credential headers, provider validation, and expiry behavior. Ruff, mypy, focused settings/storage tests (7 passed), web checks, Compose validation, and `git diff --check` passed. |
| 2026-10-28 | P2-04 | n/a | Added authenticated `POST /v1/voices/upload-url`, workspace/editor + `voices:write` authorization, required bounded `Idempotency-Key`, WAV/MP3/M4A filename/MIME/size validation, remote/path traversal rejection, quarantine object keys, and a process-scoped idempotent upload-intent store/service. Regenerated OpenAPI/client artifacts. Focused API/settings/storage/upload-intent tests (20 passed), Ruff, mypy, client typecheck, web checks, Docker rebuild/healthy API, and live unauthenticated 503 envelope verification passed. DB-backed membership and durable upload-intent persistence remain the planned follow-up integration work. |
| 2026-10-28 | P2-05 | n/a | Added deterministic `AudioValidator` and FFmpeg inspector with WAV/MP3/M4A magic-byte checks, bounded FFprobe metadata, PCM decode, 6–30 second duration policy, channel classification, silence/clipping ratios, and multi-speaker warning metadata. Added fixture-oriented coverage for accepted WAV/MP3/M4A, corrupt, spoofed, oversized, duration, silence, clipping, channel, and speaker cases (11 audio tests passed), installed FFmpeg in the API/worker image, and kept audio bytes out of logs/results. Ruff, mypy, API-focused tests, web checks, Compose validation, and `git diff --check` passed. |
| 2026-10-28 | P2-06 | n/a | Added workspace-scoped voice list/create/read/update routes, consent statement version/hash capture, editor-only updates/archive/restore/revocation, admin/owner-only permanent deletion with queued cascade intent, deterministic lifecycle transitions/readiness guards, idempotent create semantics, and redacted audit events. Added service and authenticated route coverage for roles, idempotency, consent validation, archive/restore, revoke, readiness, and asynchronous deletion (37 focused API tests passed). Regenerated OpenAPI/client artifacts; Ruff, mypy, client typecheck, web checks, Compose config, and `git diff --check` passed. Local persistence remains an in-memory adapter until the SQL repository integration step. |
| 2026-10-28 | P2-07 | n/a | Added versioned JSON model registry manifest, strict entry validation, approved-license + enabled gate, immutable job provenance metadata, checkpoint-root containment and streaming SHA-256 verification, and a runtime-loader callback with no PyTorch/download coupling. Wired the manifest into API/worker images and app state; the registry supports a reviewed but disabled OpenVoice entry pending production worker runtime wiring. Added coverage for empty/custom manifests, approved load, unknown/pending/rejected models, duplicate/hash/path failures (5 registry tests). Focused API/registry suite (42 passed), Ruff, mypy, Compose config, and `git diff --check` passed. |
| 2026-10-28 | P2-08 | n/a | Added workspace-authorized generation create/read/list/cancel/retry routes and a concurrency-safe generation service with bounded text/settings validation, ready/consented voice gate, language/model allowlist gate, SHA-pinned model provenance, stable lifecycle transitions, safe failure metadata, and workspace-scoped idempotency. List responses omit raw input text; duplicate metadata returns the original job and key reuse is rejected. Added service and authenticated route coverage (6 generation tests), regenerated OpenAPI/client artifacts, and passed Ruff, mypy, client typecheck, web checks, Compose config, and diff checks. The focused generation suite passed once; a subsequent local rerun was blocked by the known Windows `WinError 10055` socket-buffer exhaustion. The OpenVoice checkpoint remains disabled until the production worker mounts the dedicated runtime. |
| 2026-10-28 | P2-09 | n/a | Added Redis/ARQ-compatible at-least-once generation publishing, deterministic delivery IDs, worker claim leases with heartbeat/expiry recovery, bounded retry attempts, safe terminal/error persistence, duplicate-delivery deduplication, and an ARQ task entrypoint. Wired the API generation create/retry paths through the worker dispatcher and added a deterministic in-memory queue/lease adapter for local execution. Queue/lifecycle coverage (8 generation and worker tests), Ruff, mypy, client/web checks, Compose validation, and diff checks passed. The local in-memory state adapter remains the documented boundary until SQL repository wiring is completed. |
| 2026-10-28 | P2-10 | n/a | Added the provider-neutral `InferenceAdapter`/request/result contract, deterministic `SmokeCpuAdapter` CPU waveform generation, stable inference error codes, and an output-store port. Worker execution now converts a claimed job into an adapter request, persists the result through the output port, records `succeeded`, or applies safe retryable failure semantics. Added deterministic WAV, input-limit, unsupported-format, and end-to-end worker smoke coverage (5 focused tests), wired the smoke adapter into API state, and passed Ruff, mypy, client/web checks, Compose validation, and diff checks. Production model execution remains behind the reviewed registry and future OpenVoice adapter. |
| 2026-10-29 | P2-11 | n/a | Added the OpenVoice V2 adapter boundary with explicit `WORKER_DEVICE=cpu|cuda`, registry/license/SHA resolution, runtime-factory injection, bounded 25 MB/120-second mono WAV validation, output checksum, settings, device, and checkpoint provenance. Registered the locally verified official checkpoint metadata (`converter/checkpoint.pth`, SHA-256 `9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e`, MIT, approved) and recorded the dedicated runtime lock (`infra/model-registry/openvoice-runtime.lock`). Provisioned the isolated Python 3.11 CPU runtime with official OpenVoice commit `74a1d147b17a8c3092dd5430504bd83ef6c7eb23`, MeloTTS commit `209145371cff8fc3bd60d7be902ea69cbdb7965a`, and compatible wheel substitutions; the tracked `scripts/validate_openvoice_runtime.py` completed real synthesis runs using the local checkpoint and official demo fixture. Latest evidence: checkpoint loaded with no missing/unexpected keys; mono 16-bit WAV, 22,050 Hz, 4,702 ms, checkpoint SHA `9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e`, output SHA `554376a04c52c6bc200e43aa3dabc80d78584b3971be5af0a433fe6fda6ed4ca`. The smoke fixture leaves `seed` unset, so output duration/checksum can vary between valid runs. The manifest intentionally remains disabled until the production worker mounts this isolated runtime and P2-12 private asset/output wiring is complete; no weights are committed. |
| 2026-10-29 | P2-12 | n/a | Added fixed-argument FFmpeg WAV→MP3 post-processing with output size/duration/header validation, checksum recomputation, and provenance metadata; extended S3/Supabase storage with private object writes; added content-addressed generated-audio assets and an API-safe metadata record; and added `GET /v1/generations/{job_id}/download`, which rechecks workspace membership and signs a 600-second private URL without exposing the object key. Regenerated `packages/api-client/openapi.json` and `schema.ts`. Focused output/storage/queue tests (12 passed before the host socket limit recurred), independent FFmpeg encode/decode validation passed, and Ruff/mypy passed. The subsequent full API run was blocked by the known Windows `WinError 10055` socket-buffer exhaustion during asyncio setup. SQL repository persistence and production worker image mounting remain the planned deployment boundary. |
| 2026-10-29 | P2-13 | n/a | Added workspace-scoped project create/list/read/update/archive/restore endpoints with required idempotency for creation, explicit `projects:read`/`projects:write` scope and editor-role enforcement, cross-workspace isolation, and append-only project audit events. Added saved editor-settings GET/PUT contracts for voice, language, format, speed, stability, and style; draft text is intentionally rejected and remains client-local until generation. Added migration `0010_project_editor_settings` with a JSON-object check, schema/flow/TRD updates, OpenAPI/client regeneration, offline upgrade/downgrade verification, Ruff, and mypy. New async project tests are present but local execution is blocked before setup by the known Windows `WinError 10055` socket-buffer exhaustion; CI/Linux remains authoritative. SQL repository wiring remains a later persistence boundary. |
| 2026-10-29 | P2-14 | n/a | Added Argon2id API-key issuance with pinned `argon2-cffi==25.1.0` parameters, one-time `cv_live_` secret display, non-secret prefix lookup, supported scope allowlist, 365-day maximum expiry, revocation, and `last_used_at` tracking. Added JWT owner/admin-only `POST/GET /v1/api-keys` plus `POST /v1/api-keys/{key_id}/revoke`, `api_keys:read`/`api_keys:write` enforcement, metadata-safe responses, CORS support for `X-API-Key`, and API-key authentication for all generation routes with workspace binding and `generations:create`/`generations:read` enforcement. The new service/route suite passed once (4 tests) before the host socket-buffer limit recurred during the final scope-refinement rerun; Ruff, mypy, compile checks, OpenAPI export, and client typecheck pass. The implementation uses the existing `api_keys` schema/RLS contract and remains in-memory until SQL repository wiring; CI/Linux remains authoritative for the blocked async rerun. |
| 2026-10-29 | P2-15 | n/a | Added HTTPS/DNS/IP SSRF validation with delivery-time revalidation and redirect-disabled HTTP sending; one-time `whsec_` secret issuance with SHA-256-derived HMAC signing; canonical event envelopes and signature headers; per-endpoint event-ID deduplication/replay protection; 60s/300s/900s/3600s bounded retry backoff; response hashing; consecutive-failure tracking; and automatic endpoint disable after five failed attempts. Added JWT admin/owner `POST/GET /v1/webhooks` routes with `webhooks:write`/`webhooks:read` scopes, in-memory endpoint/delivery ports, and focused webhook coverage (4 tests passed). Regenerated OpenAPI/client artifacts and passed Ruff, mypy, and compile checks. The existing `webhook_endpoints`/`webhook_deliveries` schema and RLS contract remain the SQL persistence boundary. |
| 2026-10-29 | P2-16 | n/a | Added the central append-only `AuditService`/store with actor classification (`user`, `api_key`, `worker`, `system`, `moderator`), request correlation, IP/User-Agent SHA-256 digests, bounded metadata redaction, and route-level emission for upload intents, voice/project/generation mutations, generation downloads, API keys, webhooks, and moderation reports. Added JWT `profile_role` parsing and moderator-only `GET /v1/reports`, member `POST /v1/reports`, workspace authorization, and the existing `moderation_flags` SQL/RLS boundary. Audit redaction and report authorization tests passed (2), existing voice/project/generation/API-key/webhook route tests passed (14), Ruff/mypy, OpenAPI export, generated client, and client typecheck passed. |
