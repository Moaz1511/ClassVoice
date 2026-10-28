# 04 — Technical Requirements Document

**Product:** ClassVoice  
**Document status:** Locked baseline v1.0  
**Last updated:** 2026-10-27  
**Version policy:** Exact pins below are the baseline. Upgrade only through an ADR, dependency review, and green CI.

## 1. Architecture decision summary

ClassVoice uses a modular monorepo with a Next.js web app, a FastAPI control-plane API, an asynchronous job worker, and a provider-neutral inference adapter. Supabase provides managed Postgres, Auth, and private Storage for the first deployment. Local Docker Compose is the default developer environment; an NVIDIA 1660 Ti and Kaggle-compatible GPU are supported worker targets.

```text
Browser / AI agent
        |
        v
Next.js web --------------------------+
        |                              |
        | HTTPS                        | Supabase Auth session
        v                              v
FastAPI API ---> PostgreSQL (RLS)   Supabase Auth/Storage
        |
        +--> Redis queue ---> Inference worker (CUDA or CPU)
                                      |
                                      +--> private audio objects
                                      +--> model registry/checkpoints
```

The browser never talks directly to the GPU worker. The API is the authority for authorization, consent, job creation, signed URLs, and audit events.

## 2. Locked technology stack

### 2.1 Runtime and infrastructure

| Area | Exact baseline | Decision |
|---|---|---|
| Web runtime | Node.js `24.22.1` LTS | Current LTS line; use `.nvmrc` and CI check |
| Python runtime | CPython `3.13.14` | Stable GPU/library compatibility baseline |
| Database | PostgreSQL `17.11` | RLS, JSONB, UUID, full-text primitives |
| Cache/queue | Redis `7.4.2` | Short-lived queue state and rate limits; database remains source of truth |
| Containers | Docker Compose spec `2.29` | Local parity for web, API, worker, Postgres, Redis, and LocalStack S3 |
| Object storage (dev) | LocalStack `4.10.0` (S3 service) | S3-compatible private bucket locally; selected because the official MinIO image is unavailable from the current registry |
| Object storage (hosted) | Supabase Storage `v1` | Signed URLs and Postgres-backed access policies |

### 2.2 Web application

| Package | Version | Use |
|---|---:|---|
| Next.js | `16.4.3` | App Router, SSR, route handlers for thin BFF concerns |
| React | `19.3.0` | UI runtime |
| TypeScript | `5.9.3` | Strict static typing |
| Tailwind CSS | `4.1.14` | Utility styling mapped to UI tokens |
| TanStack Query | `5.90.6` | Server state, retries, cache invalidation |
| React Hook Form | `7.66.0` | Form state and accessible errors |
| Zod | `4.1.12` | Shared request/response validation at web boundary |
| Vitest | `3.2.4` | Unit/component tests |
| Playwright | `1.55.1` | Browser integration tests |
| ESLint | `9.38.0` | Linting with flat config |

Rules:

- `strict: true`; no `any` in application code without a documented boundary exception.
- Use Server Components by default; use Client Components only for interactive/editor/audio behavior.
- Do not put service-role credentials in the browser or Next.js public environment variables.
- API schemas are generated from FastAPI OpenAPI and checked into `packages/api-client`.
- `packages/api-client/openapi.json` is exported from `app.main:app.openapi()` by
  `scripts/export_openapi.py`; `openapi-typescript@7.13.0` generates
  `packages/api-client/src/schema.ts`, and `openapi-fetch@0.17.0` provides the
  typed runtime transport. Never hand-edit generated files.

### 2.3 API and worker

| Package | Version | Use |
|---|---:|---|
| FastAPI | `0.156.8` | HTTP API and OpenAPI |
| Uvicorn | `0.36.0` | ASGI server |
| Pydantic | `2.14.1` | Validation and serialization |
| SQLAlchemy | `2.1.6` | Async ORM/query layer |
| Alembic | `1.17.1` | Schema migrations |
| asyncpg | `0.30.0` | PostgreSQL driver |
| redis-py | `6.4.0` | Redis client |
| arq | `0.27.2` | Async job queue worker |
| httpx | `0.28.1` | Outbound HTTP with timeouts |
| structlog | `25.4.0` | JSON structured logs |
| boto3 | `1.43.120` | SigV4 presigned URLs for private S3-compatible storage |
| pytest | `8.4.2` | Unit/integration tests |
| ruff | `0.14.2` | Formatting/linting |
| mypy | `1.18.2` | Type checking |

API conventions:

- REST under `/v1`; JSON responses use an envelope `{data, error, request_id}`.
- OpenAPI is the contract; generated TypeScript client is not handwritten.
- `npm run api-client:check` regenerates the snapshot and client, then fails if
  either checked-in artifact differs. The API CI job runs this gate on every push
  and pull request.
- Every mutation accepts `Idempotency-Key` where duplicate work is possible.
- `POST /v1/voices/upload-url` accepts only 1–25,000,000-byte WAV/MP3/M4A
  metadata, requires an editor-level `voices:write` authorization, and returns a
  quarantine-bucket signed PUT URL. Remote URLs, path traversal, MIME/extension
  mismatches, and missing or reused idempotency keys are rejected.
- Voice lifecycle routes require a consent statement version and SHA-256
  attestation hash at creation,
  expose workspace-scoped reads, restrict updates/archive/revocation to editors,
  restrict permanent deletion to admins/owners, enforce explicit status
  transitions, append redacted audit events, and enqueue asynchronous cascade
  deletion intents. Local API state is an in-memory adapter until the SQL
  repository is connected.
- Async generation returns `202 Accepted` with a job resource.
- Timeouts: browser 30 s for normal API calls; worker outbound calls 15 s; storage signed URLs 10 minutes.
- Model execution is gated by the repository-controlled `infra/model-registry/manifest.json`.
  Each entry includes model key/version, relative checkpoint path, lowercase SHA-256,
  runtime, supported languages, configuration, and license-review status. Only
  `enabled: true` entries with `license_review_status: approved` can resolve.
  The checkpoint loader rejects unknown identities, path escapes, missing files,
  and SHA mismatches before invoking a runtime loader; no request-time downloads
  are permitted. Model provenance returned by the registry is copied to jobs.

### 2.4 Audio and inference baseline

| Component | Exact baseline | Notes |
|---|---:|---|
| PyTorch | `2.7.1` | CUDA-enabled build in GPU image; CPU fallback in dev |
| CUDA runtime | `12.6` | NVIDIA 1660 Ti uses compute capability 7.5 |
| torchaudio | `2.7.1` | Audio tensor utilities |
| FFmpeg | `7.1.5-0+deb13u1` | Sandboxed transcode/normalization |
| librosa | `0.11.0` | Quality metrics and silence/clipping checks |
| soundfile | `0.13.1` | WAV I/O |
| Model adapter | OpenVoice V2 adapter, checkpoint pinned by SHA | Provider-neutral interface; checkpoint license must be reviewed |

Inference constraints for the MVP:

- Reference audio: 6–30 seconds, one speaker, clear speech, max 25 MB.
- The validation worker first checks magic bytes/container identity, then probes
  metadata and decodes bounded PCM through `ffprobe`/`ffmpeg`; it classifies
  duration, channel count, silence, clipping, and multi-speaker warnings without
  logging audio bytes. The API image installs the FFmpeg runtime for the worker.
- Text: max 10,000 Unicode characters per job.
- Default output: WAV 24 kHz mono; MP3 is a post-process derivative.
- 16-bit inference and CPU fallback are supported; no training/fine-tuning in the product path.
- A model checkpoint is immutable once a generation is created; store model ID and SHA on the job.
- Do not download arbitrary model files at request time. Workers use an allowlisted registry manifest.

The final checkpoint is a launch gate: quality, latency, GPU memory, and model/data license must be recorded in an ADR before production use.

## 3. Repository structure

```text
/
├─ apps/
│  ├─ web/                         # Next.js App Router
│  │  ├─ app/                      # routes and layouts
│  │  ├─ components/               # UI components
│  │  ├─ features/                 # feature-level client logic
│  │  ├─ lib/                      # auth, API client, theme, telemetry
│  │  └─ tests/                    # Playwright and component tests
│  └─ api/                         # FastAPI application
│     ├─ app/
│     │  ├─ api/v1/                # routers and dependencies
│     │  ├─ core/                  # settings, auth, logging, errors
│     │  ├─ db/                    # session, models, repositories
│     │  ├─ domains/               # voices, generations, projects, keys
│     │  ├─ workers/               # arq tasks and lifecycle handlers
│     │  ├─ inference/             # adapter interface and implementations
│     │  └─ main.py
│     └─ tests/
├─ packages/
│  ├─ api-client/                  # generated TypeScript client
│  ├─ contracts/                   # shared enums and error codes
│  └─ ui/                          # design-system primitives
├─ db/
│  ├─ migrations/                  # Alembic SQL migrations
│  ├─ seed/                        # local-only fixtures
│  └─ policies/                    # reviewed RLS SQL
├─ infra/
│  ├─ docker/                      # Dockerfiles and Compose
│  ├─ model-registry/              # allowlist manifests, no weights in git
│  └─ observability/
├─ docs/                           # this context architecture
├─ scripts/                        # safe local automation
├─ .env.example
├─ CODEX.md
└─ .cursorrules
```

Dependency direction:

```text
routes -> application services -> domain ports -> adapters
                         |-> repositories -> database
                         |-> queue publisher -> worker
```

Routers do not contain inference logic, SQL string construction, or policy decisions duplicated from domain services.

## 4. External services and APIs

### Required in MVP

- **Supabase Auth:** email/password and OAuth session issuance; browser receives only the anon/public key.
- **Supabase Postgres:** database and RLS. The API uses a restricted database role; migrations use a separate admin connection.
- **Supabase Storage or S3-compatible storage:** private `voice-inputs`, `voice-derived`, `generated-audio`, and `exports` buckets.
- **Redis:** queue, short-lived locks, rate-limit counters.

### Authentication configuration contract

The repository supports two explicit authentication profiles. Local and CI use the
deterministic in-memory provider; deployed environments set
`CLASSVOICE_AUTH_PROVIDER=supabase` and provide real Supabase credentials through
secret storage. The API validates the contract before startup and never logs secret
values.

| Variable | Local default | Supabase profile |
|---|---|---|
| `CLASSVOICE_AUTH_PROVIDER` | `local` | `supabase` |
| `CLASSVOICE_AUTH_EMAIL_CONFIRMATION` | `true` | `true` (required before private resources) |
| `CLASSVOICE_AUTH_REDIRECT_ALLOWLIST` | `http://localhost:3000/auth/callback` | Exact HTTPS callback URLs only |
| `CLASSVOICE_AUTH_VERIFICATION_TTL_SECONDS` | `86400` | `86400` |
| `CLASSVOICE_AUTH_PASSWORD_RESET_TTL_SECONDS` | `3600` | `3600` |
| `CLASSVOICE_AUTH_SESSION_TTL_SECONDS` | `3600` | `3600` |
| `NEXT_PUBLIC_SUPABASE_URL` | placeholder only | Required project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | placeholder only | Required browser-safe anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | placeholder only | Required API-only secret |
| `SUPABASE_JWT_SECRET` | unset | Required API-only HS256 verification secret |
| `SUPABASE_JWT_ISSUER` | derived/optional | Defaults to `<project-url>/auth/v1` |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | Exact JWT audience claim |
| `SUPABASE_JWT_CLOCK_SKEW_SECONDS` | `30` | Small validation grace period |

For the hosted Supabase project, enable email confirmation, configure password-reset
redirects to an allowlisted `/auth/reset-password` callback, and enable only the
approved OAuth providers (`google` and `github`). Callback URLs are exact matches;
wildcards, query strings, fragments, and non-local HTTP URLs are rejected. Local
tests exercise sign-up, verification, sign-in/out, reset, OAuth state, redirect
allowlisting, and expired-session behavior without contacting Supabase or sending
real email.

API authorization accepts only HS256 Supabase access tokens with a valid signature,
issuer, audience, `authenticated` role, UUID `sub`, `iat`, and `exp` claims. The
verified subject is resolved to a workspace membership in the database; JWT role
claims are never treated as workspace roles. Each protected operation then checks
the requested workspace, minimum membership role, and explicit scope dependency.

### API runtime contract

The FastAPI process validates `APP_ENV`, `API_HOST`, `API_PORT`, `DATABASE_URL`,
`REDIS_URL`, `STORAGE_PROVIDER`, `S3_ENDPOINT`, `CORS_ORIGINS`, and the request-ID
header before serving traffic. Local defaults target the Compose services; production
must use a non-local PostgreSQL URL and an explicit, non-wildcard CORS origin list.
Every response uses `{data, error, request_id}`, every request receives a bounded
`X-Request-ID` correlation value, and `/health/live` plus `/health/ready` are always
available (interactive API docs are disabled in production).

### Optional/operational

- **Sentry `10.28.0`:** error reporting with text/audio payloads redacted.
- **Resend `6.5.0`:** transactional verification and export email; can be replaced by SMTP in self-hosted mode.
- **OpenTelemetry `1.38.0`:** traces and metrics; no raw text or audio attributes.

No external TTS API is required. If a provider adapter is added later, it must declare data residency, retention, consent, and license behavior and be disabled by default.

## 5. Security requirements

### Identity and authorization

- Supabase Auth JWT is validated by issuer, audience, signature, expiry, and `sub`.
- Browser sessions use secure, HTTP-only cookies where possible; never store access tokens in `localStorage`.
- Every request resolves `user_id`, workspace membership, role, and required scope before loading a resource.
- Service-role/database-owner credentials are server-only and never sent to the client.
- API keys are shown once, stored as Argon2id hashes, and identified by a non-secret prefix.

### Audio/data protection

- Storage buckets are private. Download URLs expire in 10 minutes and are minted only after authorization.
- Storage uses the `StorageAdapter` port: LocalStack/S3 uses boto3 SigV4 presigning;
  Supabase uses server-only Storage signed-object endpoints. Upload and download
  URLs are always short-lived (exactly 600 seconds), and object keys are rejected
  when they contain traversal, absolute paths, control characters, or unknown buckets.
- Uploads are streamed to quarantine, checked by magic bytes and FFmpeg, then promoted to the private bucket.
- Max upload 25 MB; reject path traversal, polyglot files, unsupported codecs, and remote URLs.
- Encrypt in transit with TLS 1.2+ and at rest through the provider; do not log raw audio, transcripts, tokens, or embeddings.
- Embeddings and derived features are sensitive; keep them server-side and delete them with the voice.

### Abuse prevention

- Consent is required and must be non-revoked before voice readiness and every generation.
- Block public-figure/celebrity impersonation requests and unsafe prompts using policy checks with an auditable result.
- Rate limits: sign-in 10/min/IP, uploads 10/hour/user, generation 20/hour/user, API 60/min/key baseline; configure per workspace.
- Queue concurrency is capped per workspace and globally; payloads include maximum text length and output duration.
- Webhooks require HTTPS, DNS/IP validation, signing secret, replay window, and exponential retry.

### Privacy and lifecycle

- Default retention: reference samples and generated audio retained until user deletion or workspace policy; exports expire after 24 hours.
- Consent revocation immediately blocks new generation; deletion is asynchronous and auditable.
- Data exports contain metadata and authorized audio only; never include internal embeddings or service secrets.
- Logs use request IDs and stable hashes, not emails or raw text where avoidable.

## 6. API surface (MVP)

```text
POST   /v1/workspaces
GET    /v1/workspaces/:workspace_id
GET    /v1/voices
POST   /v1/voices/upload-url
POST   /v1/voices
GET    /v1/voices/:voice_id
PATCH  /v1/voices/:voice_id
POST   /v1/voices/:voice_id/revoke
DELETE /v1/voices/:voice_id
POST   /v1/projects
GET    /v1/projects/:project_id
PATCH  /v1/projects/:project_id
POST   /v1/generations
GET    /v1/generations
GET    /v1/generations/:generation_id
POST   /v1/generations/:generation_id/cancel
POST   /v1/generations/:generation_id/retry
GET    /v1/generations/:generation_id/download
POST   /v1/api-keys
GET    /v1/api-keys
POST   /v1/api-keys/:key_id/revoke
POST   /v1/webhooks
GET    /v1/webhooks
```

Every endpoint has an explicit scope, request schema, response schema, error table, and audit behavior in the generated OpenAPI.

## 7. Deployment profiles

### Local development

Docker Compose runs web, API, worker, Postgres, Redis, and LocalStack S3. A `WORKER_DEVICE=cpu|cuda` flag selects the inference image. Seed data is synthetic and never contains real voice samples.

### Kaggle GPU evaluation

The worker image is exported as a reproducible notebook/container artifact. The notebook receives a short-lived job bundle, writes output to a staging bucket, and calls the API callback with a signed worker token. No long-lived service-role key is placed in a notebook.

### Pilot production

Run web/API on a managed container platform, Supabase hosted services, Redis with persistence, and one isolated GPU worker. Put the worker on a private network; expose only the API callback endpoint with mTLS or signed callbacks.

## 8. Verification and release gates

- `npm run lint`, `npm run typecheck`, `npm run test`, `npm run test:e2e`.
- `ruff check`, `mypy`, `pytest`, migration replay from an empty database.
- OpenAPI diff must be reviewed for breaking changes.
- SAST/dependency scan and secret scan must pass.
- RLS integration tests must prove cross-workspace reads/writes fail.
- Audio fixture tests must cover invalid MIME, corrupt headers, silence, clipping, multi-speaker warning, and max duration.
- Release candidate must include a model license record, consent audit test, deletion test, and rollback plan.

## 9. Version verification references

The baseline was checked against current official release pages on 2026-10-27. These links are reference material; the lockfiles and CI are the final source of truth.

- [Node.js release schedule](https://nodejs.org/en/about/previous-releases)
- [Next.js package versions](https://www.npmjs.com/package/next?activeTab=versions)
- [React package versions](https://www.npmjs.com/package/react?activeTab=versions)
- [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/)
- [Python downloads](https://www.python.org/downloads/)
- [PostgreSQL 17 documentation](https://www.postgresql.org/docs/17/)
- [Supabase Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
