# ADR-001: Approve OpenVoice V2 model license and pinned checkpoint

Status: accepted for engineering use; production enablement remains blocked

Decision date: 2026-11-01

## Context

ClassVoice needs a reproducible voice-conversion model whose terms permit the intended educational and agent-generated content use. Model approval must be independent from quality, safety, privacy, and performance approval.

## Decision

Approve the registered OpenVoice V2 2.0.0 entry under the MIT license, with the converter checkpoint pinned to:

```text
SHA-256 9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e
```

The authoritative runtime record is `infra/model-registry/manifest.json`. Runtime creation must fail if the local checkpoint differs, the license review is not `approved`, or the entry is not enabled. The entry remains `enabled: false`; this ADR does not authorize pilot deployment or bypass consent/model-quality/GPU gates.

The upstream OpenVoice repository and OpenVoice V2 model distribution identify MIT licensing and commercial-use availability. MeloTTS, used for multilingual base speech, is also distributed under MIT. Release artifacts must preserve the applicable copyright and MIT permission/warranty notice for source and weights.

## Consequences

- A different checkpoint, upstream revision, model family, fine-tune, or dataset requires a new manifest entry, checksum, provenance record, license review, and security/quality evaluation.
- Runtime downloads are prohibited; approved artifacts are acquired and verified out of band.
- The project must ship third-party notices and cannot imply that MIT approval establishes voice-owner consent or removes privacy/publicity obligations.
- Production enablement still requires active consent enforcement, durable runtime adapters, rate limiting, hosted backup proof, acceptable reference-GPU performance, and the P4-08 release decision.

## Engineering approval record

| Field | Value |
|---|---|
| Model | OpenVoice V2 |
| Registered version | 2.0.0 |
| License identifier | MIT |
| License review | Approved |
| Checkpoint SHA-256 | `9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e` |
| Runtime enabled | No |
| Approver | Repository owner/project engineering decision |

This is an engineering decision record, not legal advice.
