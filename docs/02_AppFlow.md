# 02 — Application Flow and State Machine

**Product:** ClassVoice  
**Document status:** Baseline v1.0  
**Last updated:** 2026-10-27

## 1. Route map

| Route | Auth | Purpose |
|---|---|---|
| `/` | Public | Product explanation, safety disclosure, sign-in/sign-up CTAs |
| `/auth/sign-in` | Public | Email/password and OAuth sign-in |
| `/auth/sign-up` | Public | Account creation and terms acceptance |
| `/auth/verify-email` | Public | Email verification pending/success/expired states |
| `/auth/reset-password` | Public | Request and complete password reset |
| `/onboarding` | Authenticated | Create workspace, choose role, read safety notice |
| `/dashboard` | Authenticated | Recent projects, generation status, quick actions |
| `/voices` | Authenticated | Voice profile list, filters, empty/error states |
| `/voices/new` | Authenticated | Consent, upload/record, validation, processing |
| `/voices/:voiceId` | Authenticated | Voice detail, sample preview, lifecycle actions |
| `/studio` | Authenticated | Text-to-speech generation editor |
| `/studio/:projectId` | Authenticated | Persistent project editor and output list |
| `/generations` | Authenticated | Searchable generation history |
| `/generations/:generationId` | Authenticated | Output details, player, metadata, retry/download |
| `/api-keys` | Workspace admin | Scoped API key creation/revocation |
| `/webhooks` | Workspace admin | Endpoint setup, delivery history, test event |
| `/settings/profile` | Authenticated | Profile, locale, theme, account export/delete |
| `/settings/workspace` | Workspace admin | Workspace name, members, roles, retention |
| `/settings/safety` | Workspace admin | Safety acknowledgements, moderation contacts |
| `/admin/reports` | Moderator/admin | Abuse reports and disabled resources |
| `/admin/audit` | Moderator/admin | Filterable audit log |
| `/docs/api` | Authenticated | API reference and copyable examples |
| `/404` | Public | Not found |
| `/error` | Public | Recoverable/unrecoverable application error |

## 2. Global application state

```text
BOOTING
  -> AUTH_UNKNOWN -> SIGNED_OUT | SIGNED_IN
SIGNED_IN
  -> NO_WORKSPACE -> ONBOARDING
  -> HAS_WORKSPACE -> APP_READY
APP_READY
  -> SESSION_EXPIRED -> AUTH_SIGN_IN (preserve returnTo)
  -> NETWORK_DEGRADED -> APP_READY + persistent warning
  -> FATAL_ERROR -> ERROR_SCREEN + requestId
```

Global rules:

- Route guards run before rendering protected data.
- A 401 refreshes once, then redirects to sign-in with `returnTo`.
- A 403 shows an authorization page, not a generic 500.
- Mutations use an idempotency key where the API supports it.
- Every async screen exposes Loading, Empty, Error, and Ready states.

## 3. Screen-by-screen flow

### 3.1 Landing (`/`)

**Primary actions:** `Create account`, `Sign in`, `Read safety policy`.  
**Secondary actions:** `View API docs` (public overview only).

- If already signed in, `Open dashboard` replaces auth CTAs.
- No audio is uploaded or generated from the landing page.
- Error state: if feature/config fetch fails, render static content and a `Try again` link.

### 3.2 Sign-up (`/auth/sign-up`)

Fields: email, password, password confirmation, display name, terms checkbox.

Buttons and transitions:

- `Create account` → `SUBMITTING` → `VERIFY_EMAIL_PENDING`.
- `Continue with provider` → provider redirect → `ONBOARDING` or `DASHBOARD`.
- `Already have an account` → `/auth/sign-in`.
- Password validation is client-side for feedback and server-side for truth.

Errors:

- Duplicate email: “An account already exists. Sign in or reset your password.”
- Weak password: show requirements without revealing server policy internals.
- Rate limited: disable submit for server-provided retry window.

### 3.3 Sign-in (`/auth/sign-in`)

- `Sign in` → `SUBMITTING` → `SIGNED_IN` → workspace check.
- `Continue with provider` → provider redirect.
- `Forgot password` → reset request.
- Invalid credentials use one generic message.
- Expired/invalid session → clear local token and return to sign-in.

### 3.4 Verify email (`/auth/verify-email`)

States: `PENDING`, `VERIFIED`, `EXPIRED`, `INVALID`, `RATE_LIMITED`.

- `Resend email` is disabled during a countdown and uses a rate-limited endpoint.
- `I verified` rechecks the session.
- `Back to sign in` is always available.

### 3.5 Onboarding (`/onboarding`)

Steps:

1. `WELCOME`: choose Student, Teacher, or Agent developer.
2. `WORKSPACE`: enter workspace name; a personal workspace is created by default.
3. `SAFETY`: read and acknowledge synthetic voice and consent rules.
4. `DONE`: go to dashboard.

The `Continue` button remains disabled until the current step validates. Back navigation never loses saved steps. If workspace creation fails, retain form values and show `Retry`.

### 3.6 Dashboard (`/dashboard`)

Cards: `Create voice`, `Open studio`, `Recent generations`, `Workspace usage`.

- Empty new workspace: show a three-step checklist with `Create your first voice` as the primary action.
- Loading: skeleton cards and list rows.
- Error: preserve navigation and show a per-card retry.
- A generation card opens `/generations/:generationId`.

### 3.7 Voices list (`/voices`)

Filters: status, language, owner, search.  
Actions: `Create voice`, row `Open`, kebab `Archive`, `Revoke`, `Delete`.

States:

- Empty: explain that a consented sample is required; `Create voice`.
- No filter results: `Clear filters`.
- Loading: table/list skeleton.
- Error: `Retry` without clearing filters.
- Revoked voices remain visible as historical records but cannot be selected for new generation.

### 3.8 Create voice (`/voices/new`)

State machine:

```text
CONSENT_UNREAD
  --Read and acknowledge--> CONSENT_ACCEPTED
CONSENT_ACCEPTED
  --Choose file/record--> SAMPLE_SELECTED
SAMPLE_SELECTED
  --Upload--> UPLOADING -> VALIDATING
VALIDATING
  --pass--> PROCESSING -> READY
  --fail--> SAMPLE_INVALID
SAMPLE_INVALID
  --Replace sample--> SAMPLE_SELECTED
READY
  --Open voice--> VOICE_DETAIL
```

Actions:

- `I own this voice / have permission` checkbox is mandatory.
- `View consent statement` opens a non-dismissable modal with statement version.
- `Choose audio` opens file picker; `Record sample` is P1 and may be hidden until implemented.
- `Cancel` returns to `/voices` without persisting a draft unless upload started.
- `Retry processing` reuses the asset and idempotency key.

Validation feedback must identify the reason: unsupported format, too large, too short/long, silence, clipping, multiple speakers, poor signal, or policy block. Never display an embedding or raw storage key.

### 3.9 Voice detail (`/voices/:voiceId`)

Sections: status banner, sample player, consent receipt, quality metrics, usage summary, audit timeline.

Actions:

- `Use in studio` is enabled only in `READY`.
- `Rename` is inline and optimistic with rollback.
- `Archive` is reversible and removes the voice from default selectors.
- `Revoke consent` is a two-step confirmation; it immediately blocks new jobs.
- `Delete permanently` requires typing the voice name and explains cascade deletion.

Error/empty handling:

- 404: resource not found or no longer accessible; do not reveal whether it ever existed.
- 403: “You do not have access to this voice.”
- Missing preview asset: show metadata and `Regenerate preview` only if safe/allowed.

### 3.10 Studio (`/studio` or `/studio/:projectId`)

Editor fields: project name, text, voice, language, format, speed, style/stability controls.

Actions:

- `Save project` → `SAVING` → `SAVED` or inline error.
- `Save project` persists the project name/description and the explicit editor
  settings snapshot (voice, language, format, speed, stability, and style).
  Draft text is local-only until `Generate` submits it; project APIs reject
  unknown draft fields and never persist unsaved text.
- `Generate` validates text, voice readiness, and consent; then creates a job with an idempotency key.
- `Cancel generation` is available while queued/processing; it changes the job to `CANCEL_REQUESTED`.
- `Clear` requires confirmation if unsaved text exists.

Job states shown in the output rail:

```text
CREATED -> QUEUED -> PROCESSING -> SUCCEEDED
                         |-> FAILED
                         |-> CANCEL_REQUESTED -> CANCELED
```

The editor must preserve unsaved text through refresh using a local draft keyed by project ID, but never persist raw text to analytics.

### 3.11 Generation detail (`/generations/:generationId`)

- `Play/Pause`, seek bar, volume, playback speed, `Download`, `Rename`, `Retry`, `Delete`.
- Show text character count, voice, model version, settings, created time, checksum/provenance indicator.
- Failed state shows user-safe error code, next action, and `Retry` if retryable.
- Canceled state shows who canceled it and a `Generate again` action.
- Download creates a short-lived signed URL; never expose the storage object key.

### 3.12 API keys (`/api-keys`)

- Empty: explain keys and show `Create API key`.
- Create modal fields: name, scopes, expiration.
- `Create key` displays the secret exactly once with `Copy` and download-to-file actions.
- Subsequent visits show prefix, scopes, last used, expiry, revoked state; never show the secret.
- `Revoke` requires confirmation and immediately invalidates future requests.
- Key management uses the signed-in workspace owner/admin session with `api_keys:read` or
  `api_keys:write`; machine clients send the resulting secret as `X-API-Key` only to
  generation routes, where `generations:read` and `generations:create` are checked.

### 3.13 Webhooks (`/webhooks`)

- `Add endpoint` validates the HTTPS URL, DNS result, SSRF/IP policy, and selected events;
  a server-validated endpoint appears as `active`.
- Secret is shown once, then only its prefix.
- Delivery rows show pending, delivered, retrying, failed, or abandoned; five consecutive
  failed attempts disable the endpoint and stop new deliveries.
- `Send test event` is disabled until the endpoint is verified.
- SSRF protections run server-side; private IP ranges and non-HTTPS endpoints are rejected.

### 3.14 Settings and deletion

- Profile settings save independently from workspace settings.
- `Export my data` creates an asynchronous export job and sends a notification when ready.
- `Delete account` requires password/re-authentication, typed confirmation, and explicit acknowledgement of cascade effects.
- If deletion is queued, show a cancel window only if the backend supports it; otherwise show the scheduled completion time.

## 4. Navigation and unsaved-change rules

- Browser back is safe for all read-only screens.
- Leaving Studio with unsaved text opens a confirmation dialog: `Stay`, `Discard`, `Save project`.
- Leaving an upload in progress asks whether to cancel; server-side cleanup is eventual.
- Deep links preserve the original route after sign-in, but never restore a revoked/forbidden resource.

## 5. Error taxonomy

| Code family | Meaning | UI behavior |
|---|---|---|
| `AUTH_*` | Session, credential, or verification issue | Explain recovery; never expose sensitive detail |
| `ACCESS_*` | Missing membership or scope | Show authorization message and safe navigation |
| `INPUT_*` | Invalid text, audio, or setting | Inline field error and correction path |
| `CONSENT_*` | Missing/revoked/invalid consent | Block action and link to voice detail |
| `QUOTA_*` | Rate/size/concurrency limit | Show limit and retry time |
| `JOB_*` | Queue/inference failure | Show retryability and request ID |
| `STORAGE_*` | Upload/download/object issue | Retry and support request ID |
| `POLICY_*` | Safety/moderation block | Neutral explanation; link to policy/report flow |
| `INTERNAL_*` | Unexpected server failure | Generic message plus request ID |

## 6. Empty, loading, and degraded states

Every collection screen must define:

- first-use empty state with one primary action;
- filtered empty state with `Clear filters`;
- loading skeleton that matches final layout;
- stale-data banner when cached data is shown;
- retry action that does not duplicate a mutation;
- offline/degraded banner that distinguishes “read-only cached” from “cannot save”.

## 7. Accessibility and keyboard flow

- Every modal traps focus and returns focus to its trigger.
- Upload dropzones have a keyboard-equivalent file button.
- Audio controls have text labels and keyboard shortcuts only when discoverable.
- Progress states are announced with `aria-live="polite"`; errors use `role="alert"`.
- Color is never the only status signal; pair with icon and text.
# P2-16 audit and report flows

All successful mutation and private-download screens show the existing request
correlation ID in the error/receipt context; the API emits the corresponding
central audit event without storing source text, audio bytes, signed object
keys, API-key secrets, or webhook secrets. The audit screen consumes the
workspace-admin SQL read path, while the report screen uses the following
routes:

| Action | Route | Authorization | Success | Failure/empty state |
|---|---|---|---|---|
| Submit report | `POST /v1/reports` | Authenticated workspace member | Report is `open` and a confirmation receipt is shown | `403` for a different workspace; `422` for invalid resource/reason; retain form text locally |
| Review reports | `GET /v1/reports` | JWT `app_metadata.profile_role=moderator` | Newest-first list with status filter | `403` for non-moderators; empty list uses the standard empty-state panel |

Moderator report rows contain only bounded report metadata and description. The
moderator UI must not render generation input/audio or expose private storage
URLs as part of a report review.
# P3-02 authentication implementation notes

The implemented auth screens preserve `returnTo` only as a validated internal
path. Sign-in rejects unsafe external return URLs, expired sessions redirect to
the same path with an explicit expiry message, and verification/reset errors are
shown inline without exposing account existence. The local/CI provider models
the documented state transitions; the Supabase callback replaces its transient
adapter in the hosted profile.

# P3-03 dashboard shell implementation notes

The protected App Router layout now owns the authenticated shell for all workspace routes. The sidebar and mobile navigation expose dashboard, voice profiles, Studio, generations, API keys, webhooks, reports, audit, and settings destinations. A workspace switcher is intentionally a placeholder until the workspace API is connected; it never displays a fabricated member or workspace list. A protected catch-all route provides explicit loading/empty/error-safe placeholders for list, create, and detail routes, and every placeholder states that no private data is loaded until the authenticated API client is wired.

# P3-04 voice screen implementation notes

The voice list implements status/language/owner/search filters, archived inclusion, filtered-empty recovery, loading, retry/error, and workspace-scoped data messaging. The create screen follows `CONSENT_UNREAD` → `CONSENT_ACCEPTED` → `SAMPLE_SELECTED` → upload/validation/processing states, validates WAV/MP3/M4A and the 25 MB client limit, and explains that duration, silence, clipping, channels, speaker warnings, and policy checks are server truth. The consent modal is non-dismissable until the acknowledgement action is chosen, and no raw audio or storage key is rendered. The detail screen uses safe inaccessible-resource copy and requires confirmation for consent revocation and permanent deletion.

# P3-05 Studio implementation notes

The Studio editor is available at `/studio` and `/studio/:projectId`. It persists only draft text in a project-keyed browser draft and keeps saved project metadata/editor settings separate; raw draft text is never sent to the project save contract. The editor exposes project name, language, WAV/MP3, speed, stability, style, and a 10,000-character counter. Voice selection contains only the Ready/active-consent slot; revoked, archived, processing, and not-ready voices are excluded. Save and generation states are explicit, and internal navigation plus browser unload use a Stay/Discard/Save project guard whenever the editor is dirty.

# P3-06 generation screen implementation notes

The generations list provides state and output-format filters, search by job ID, active-job auto-refresh, bounded polling backoff, and retry-safe loading/error/empty states. The detail screen maps `created`, `queued`, `processing`, `succeeded`, `failed`, `cancel_requested`, and `canceled` to distinct status copy and controls. Cancellation and retry are available only for valid lifecycle states; download/playback is available only after `succeeded` and re-authorization. Collection views never render source text, object keys, or signed URLs; output metadata is checksum/provenance-only.

# P3-07 administration screen implementation notes

The API-key screen uses the supported scope allowlist, bounded expiration choices, metadata-only list rows, one-time secret reveal/copy/dismiss state, and revoke confirmation. The browser never creates a usable key or stores a secret; the authenticated server response remains the only issuance source. The webhook screen requires HTTPS at the client boundary and repeats server-side DNS/private-address/redirect validation messaging, supports the documented event allowlist, shows the one-time signing-secret surface, and exposes pending/delivered/retrying/failed/abandoned delivery states. Test events are enabled only for active, verified endpoints.
