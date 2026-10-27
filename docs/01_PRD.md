# 01 — Product Requirements Document

**Product working name:** ClassVoice  
**Document status:** Baseline v1.0  
**Last updated:** 2026-10-27  
**Primary audience:** Product, design, frontend, backend, ML, security, and coding agents

## 1. Product summary

ClassVoice lets a student, teacher, or approved AI agent create clear academic narration from text using a voice that the owner has explicitly consented to clone. It combines a ElevenLabs-style studio experience with an API that agents can call to generate and retrieve audio.

The MVP is deliberately narrower than a general-purpose voice marketplace:

1. A user creates a private workspace.
2. A user records or uploads a short reference sample and completes an explicit consent declaration.
3. The system validates the sample, creates a private voice profile, and makes it available only to authorized workspace members.
4. The user enters academic text, chooses a voice and delivery controls, submits a generation job, previews the result, and downloads the audio.
5. An authorized AI agent can do the same through scoped REST API keys.
6. Every voice and output has an auditable provenance trail and can be deleted by the owner.

## 2. Core problem

Academic content creators repeatedly record the same explanatory material, while students and AI agents need accessible audio versions of notes, lessons, and revision material. Existing tools are either:

- optimized for entertainment and public voice marketplaces;
- too expensive or opaque for student use;
- difficult to run privately on modest hardware; or
- unsafe because they do not prove consent or provide strong abuse controls.

ClassVoice solves the workflow problem while treating a person’s voice as sensitive biometric-like data: explicit consent, private-by-default access, traceable use, and deletion are first-class requirements.

## 3. Target personas

### 3.1 Student learner — primary MVP persona

- Creates audio revision notes from their own text.
- May use their own voice or a teacher-provided voice with documented permission.
- Has limited budget and may use a browser plus an NVIDIA 1660 Ti or a shared Kaggle GPU.
- Values speed, clarity, exportability, and simple controls over cinematic voice acting.

### 3.2 Teacher/content creator — primary MVP persona

- Records one approved voice profile and generates lessons, summaries, and accessibility narration.
- Needs predictable pronunciation, repeatable settings, project history, and easy download.
- Must be able to revoke the voice and delete all derived outputs.

### 3.3 AI agent/integration developer — secondary MVP persona

- Calls a REST API to turn structured academic text into audio.
- Needs scoped keys, idempotency, job polling/webhooks, and machine-readable errors.
- Must not be able to create or use a voice without a workspace-level permission and an existing consent record.

### 3.4 Workspace administrator/moderator — operational persona

- Reviews abuse reports and generation failures.
- Can disable a voice/workspace, inspect audit events, and enforce retention.
- Cannot download private audio unless an explicit break-glass procedure is recorded.

## 4. MVP goals

### 4.1 User goals

- Produce a usable 30–120 second academic narration in under 90 seconds on the target GPU for a normal request.
- Create a voice profile from one consented reference sample with clear quality feedback.
- Keep voice profiles, scripts, and generated audio private by default.
- Let an AI agent generate audio without exposing browser session cookies.
- Make all generated outputs reproducible through saved settings and model version metadata.

### 4.2 Business/quality goals

- Establish a trustworthy consent and provenance model before adding scale.
- Keep the core inference path provider-neutral so the project can run on local GPU, Kaggle, or a future GPU worker.
- Make the product useful without requiring a paid third-party TTS API.

## 5. MVP user stories

### Authentication and workspace

- **US-001:** As a new user, I can sign up with email/password or a supported OAuth provider and verify my email.
- **US-002:** As a user, I can create or rename my personal workspace and invite a collaborator by email.
- **US-003:** As a user, I can sign out, reset my password, and delete my account after confirming the destructive action.

### Consent and voice profiles

- **US-010:** As a voice owner, I can read the consent statement, affirm that I own or have permission to use the sample, and record the statement version and timestamp.
- **US-011:** As a user, I can upload one WAV/MP3/M4A reference sample up to 25 MB and receive validation feedback.
- **US-012:** As a user, I can see a voice profile status: Draft, Processing, Ready, Rejected, Revoked, or Archived.
- **US-013:** As a user, I can rename, archive, revoke, or permanently delete a voice profile and its derived audio.
- **US-014:** As a user, I cannot publish a voice publicly in MVP; all sharing is workspace-scoped.

### Generation studio

- **US-020:** As a user, I can paste or type academic text up to 10,000 Unicode characters.
- **US-021:** As a user, I can select a Ready voice, language, output format, speed, and stability/style controls.
- **US-022:** As a user, I can submit a generation job and see queued, processing, succeeded, failed, or canceled state.
- **US-023:** As a user, I can play, pause, seek, download, and rename a successful output.
- **US-024:** As a user, I can retry a failed job without duplicating a billable/usage event.
- **US-025:** As a user, I can see the exact voice/model/settings used for an output.

### Projects and history

- **US-030:** As a user, I can save text and generation settings in a project.
- **US-031:** As a user, I can filter generation history by project, voice, status, and date.
- **US-032:** As a user, I can export a project’s audio and metadata as a ZIP or download individual files.

### Agent API

- **US-040:** As a workspace admin, I can create a scoped API key with an expiry and scopes such as `voices:read`, `generations:create`, and `generations:read`.
- **US-041:** As an agent, I can submit an idempotent generation request and poll or receive a webhook for completion.
- **US-042:** As an admin, I can revoke an API key and see its last-used time.

### Safety and account controls

- **US-050:** As a user, I can export my data and request deletion.
- **US-051:** As a moderator, I can flag or disable a voice/workspace and preserve an audit reason.
- **US-052:** As a user, I see an explicit disclosure that generated speech is synthetic and must not be used to impersonate a person without permission.

## 6. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | Email/OAuth authentication with verified-email gate before voice creation | P0 |
| FR-02 | Workspace membership and role checks on every private resource | P0 |
| FR-03 | Consent record required before a voice can reach Ready | P0 |
| FR-04 | Audio validation: extension, MIME, magic bytes, duration, sample rate, channel count, silence, clipping | P0 |
| FR-05 | Async generation jobs with idempotency and durable status | P0 |
| FR-06 | Private object storage with signed, short-lived download URLs | P0 |
| FR-07 | REST API for voice read and generation create/read/cancel | P0 |
| FR-08 | Audit events for consent, voice lifecycle, generation, downloads, key changes, and deletion | P0 |
| FR-09 | User-visible error codes and actionable recovery text | P0 |
| FR-10 | Downloadable WAV and MP3 output | P1 |
| FR-11 | Webhook delivery with retry and signature verification | P1 |
| FR-12 | Project organization and ZIP export | P1 |

## 7. Non-functional requirements

- **Privacy:** No voice or generated object is public by default. Do not send audio to an external inference provider unless the user explicitly enables that provider.
- **Performance:** P95 API read latency < 400 ms excluding generation; P95 queue-to-first-audio target < 90 s for 30–120 s text on the reference GPU.
- **Reliability:** A generation job is never silently lost; every terminal state is persisted.
- **Accessibility:** WCAG 2.2 AA target for keyboard navigation, contrast, focus, and screen-reader labels.
- **Reproducibility:** Store model version, inference parameters, input text hash, and output checksum for every generation.
- **Portability:** Run the control plane with Docker Compose and run inference on local CUDA or Kaggle-compatible workers.
- **Observability:** Structured logs, traces for API/job IDs, metrics for queue time, inference time, failures, and storage usage.
- **Data lifecycle:** User can revoke consent and delete a voice; deletion must cascade to derived embeddings and outputs after the configured retention window.

## 8. Success metrics

### Activation and usefulness

- 70% of verified users create a Ready voice within 10 minutes of first sign-in.
- 80% of first-time users complete a successful generation within 15 minutes.
- At least 60% of generated outputs are downloaded or played to completion.

### Quality and performance

- >= 90% of valid reference samples pass automated quality checks without manual intervention.
- <= 5% of generation jobs fail for platform reasons (excluding invalid user input and policy blocks).
- P95 queue-to-complete under 90 s for the reference workload and <= 10,000 characters.
- Human evaluator mean opinion score >= 3.5/5 for intelligibility on academic narration samples.

### Trust and safety

- 100% of Ready voices have a non-revoked consent record.
- 100% of private downloads use an authenticated, short-lived signed URL.
- 100% of destructive actions create an audit event.
- Critical abuse reports acknowledged within one business day during pilot.

### Developer experience

- An agent can create a key, submit a request, and retrieve audio using only the API docs and a sample curl command.
- API contract tests cover every documented P0 endpoint.

## 9. Explicit safety policy

The MVP supports only voices for which the requester has ownership or documented permission. The UI and API must:

- require a consent declaration and store its version;
- block celebrity/public-figure impersonation and requests that claim to bypass consent;
- add synthetic-speech provenance metadata and a visible “AI-generated” label in the product;
- rate-limit bulk generation and retain audit records;
- provide report, revoke, export, and delete paths;
- avoid exposing embeddings or raw reference URLs to clients.

This is a product requirement, not a moderation afterthought.

## 10. Out of scope (non-goals)

The following are explicitly not part of MVP and must not be implemented unless this document is amended:

1. Public voice marketplace, voice discovery, follower counts, or monetization.
2. Celebrity, public-figure, deceased-person, or “sound exactly like X” presets.
3. Voice conversion, live voice changers, microphone-to-microphone streaming, or telephony.
4. Real-time conversational agents, interruption handling, or speech-to-speech dialogue.
5. Training a foundation TTS model or fine-tuning a model per user.
6. Automatic scraping/import of audio from URLs, social networks, or cloud drives.
7. Mobile-native apps, browser extensions, desktop apps, or offline-only distribution.
8. Multi-region active-active deployment, enterprise SSO/SCIM, legal hold, or HIPAA/FERPA certification.
9. Subscriptions, billing, credit packs, or commercial usage metering beyond internal usage events.
10. Automatic translation, dubbing, lip-sync, music generation, sound effects, or background ambience.
11. Unmoderated bulk/API access, anonymous generation, or API keys without workspace scope.
12. Guaranteeing that any third-party model or checkpoint is commercially licensed; every model must pass a separate license review.
13. Copying ElevenLabs branding, proprietary UI trade dress, private APIs, or proprietary model behavior; “like ElevenLabs” means comparable workflow capability, not a literal clone.

## 11. Open decisions that are intentionally deferred

- Which consent evidence is legally sufficient in each launch jurisdiction.
- The final inference checkpoint after latency, quality, and license bake-off.
- Whether a school workspace requires a separate administrator approval flow.
- Production hosting provider and GPU autoscaling policy.

These decisions must not block the local MVP, but they must be recorded in an ADR before production launch.
