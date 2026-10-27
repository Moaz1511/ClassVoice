# ClassVoice Coding-Agent Contract

This repository is a consent-first academic voice generation product. Before changing code, configuration, migrations, tests, or infrastructure, the coding agent must read all six context documents in this order:

1. [`docs/01_PRD.md`](docs/01_PRD.md) — product boundaries, personas, safety, and non-goals
2. [`docs/02_AppFlow.md`](docs/02_AppFlow.md) — routes, state machines, actions, and failure states
3. [`docs/03_UI_Spec.md`](docs/03_UI_Spec.md) — visual tokens, component states, and accessibility
4. [`docs/04_TRD.md`](docs/04_TRD.md) — locked stack, structure, APIs, and security constraints
5. [`docs/05_Schema.md`](docs/05_Schema.md) — tables, relationships, indexes, Auth, and RLS
6. [`docs/06_Plan.md`](docs/06_Plan.md) — dependency-ordered implementation checklist

## Non-negotiable operating rules

- Do not write implementation code until the six documents have been read for the current task.
- Treat the six documents as the architecture source of truth. If code and a document disagree, stop and resolve the document/ADR before silently choosing a third behavior.
- Execute [`docs/06_Plan.md`](docs/06_Plan.md) in order. Do not skip dependencies or mark a step complete because files merely exist.
- After every completed plan step, immediately update `docs/06_Plan.md`: change `[ ]` to `[x]`, add the date, commit/PR identifier, verification command, and concise evidence in the progress log.
- If a task changes requirements, routes, tokens, stack, schema, security, or scope, update the affected context document and record an ADR before implementation continues.
- Preserve unrelated user changes. Never reset, delete, or overwrite broad paths without explicit authorization.

## Product and safety invariants

- Every Ready voice has a non-revoked consent record.
- Voice profiles, reference audio, embeddings, scripts, and generated audio are private by default and workspace-scoped.
- No celebrity/public-figure impersonation, consent bypass, anonymous generation, or unscoped API key.
- Never log raw audio, raw reference URLs, access tokens, API-key secrets, embeddings, or full user text.
- Storage object keys and service-role credentials never reach the browser.
- Re-check authorization, voice status, consent, model allowlist, and idempotency on the server for every generation request.
- Deletion and consent revocation must be auditable and eventually remove derived assets according to the retention policy.

## Implementation conventions

- Use the exact versions and dependency direction in `docs/04_TRD.md`.
- Keep routers thin: route → application service → domain port → adapter/repository.
- Use generated OpenAPI clients; do not hand-maintain duplicate request/response types.
- Make async work durable: the database is the source of truth, Redis is coordination only.
- Use semantic UI tokens from `docs/03_UI_Spec.md`; do not introduce arbitrary hex values in components.
- Implement Loading, Empty, Error, Ready, and degraded states for every async screen described in `docs/02_AppFlow.md`.
- Add or update tests with each behavior change. Prefer a focused test command first, then the full required gate.

## Handoff format

When reporting work, include:

1. The plan step(s) completed.
2. Files changed and why.
3. Verification commands and results.
4. Any security/privacy review performed.
5. The next unblocked step in `docs/06_Plan.md`.

If blocked, identify the exact dependency or decision, do not invent a workaround that changes the architecture, and add a `[!]` note to the plan until the decision is resolved.
