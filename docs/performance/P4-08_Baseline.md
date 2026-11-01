# P4-08 pilot metrics baseline

Status: preflight blocked; hosted pilot measurements not yet available

## Verified engineering baseline

| Metric | Current evidence | Target | Status |
|---|---:|---:|---|
| Authenticated API read P95 | 4.951 ms over 200 in-process requests | < 400 ms | Engineering pass; repeat over hosted network |
| Authorization-checked signed URL P95 | 35.984 ms over 100 local S3-signing requests | < 400 ms operational guardrail | Engineering pass; repeat with hosted storage |
| 10,000-character API acceptance P95 | 6.499 ms over 24 requests | < 400 ms operational guardrail | Engineering pass |
| Synthetic queue completion | 24/24, concurrency 4, no duplicate outputs | No lost jobs or duplicate outputs | Engineering pass |
| OpenVoice short CUDA probe | 7.721 seconds of generated audio | Informational | Pass for checkpoint/runtime proof only |
| OpenVoice 10,000-character CUDA run | Exceeded 180-second hard timeout | P95 < 90 seconds | Known gap; pilot blocker pending ADR-003 |
| Production dependency/security gates | GitHub Actions run 41317828747 at commit `55a623a947dd10b3166abb04d84df3db083e1500` | Green exact-SHA CI | Pass for P4-07 commit |

The latency figures are from the P4-06 local ASGI/control-plane harness and are not hosted SLO evidence. The GPU result is from the GTX 1660 Ti reference machine. See `docs/performance/P4-06_Results.md` for methodology and redaction constraints.

## Hosted baseline required before tagging

| Metric | Required evidence | Threshold |
|---|---|---|
| API reads | At least 200 authenticated hosted requests | P95 < 400 ms |
| Signed downloads | At least 100 authorized hosted signing requests | P95 < 400 ms and TTL = 600 s |
| Generation | Accepted maximum from ADR-003 on approved GPU/model | P95 queue-to-complete < 90 s or explicitly rejected release |
| Reliability | Pilot window jobs grouped by platform/user/policy outcome | Platform failures <= 5% |
| Privacy | Ready voice and download audit queries | 100% active consent; 100% short-lived authenticated URLs |
| Abuse protection | Request/character quota counters and 429/503 drill | Shared Redis enforcement; hosted failure is fail-closed |
| Storage | Private input/derived/output/export bytes and lifecycle | No public objects; retention configured |
| Recovery | Hosted PITR/object restore and rollback rehearsals | RPO <= 15 min; RTO <= 4 h |

Populate the private release evidence with aggregate measurements and hashes only. Do not store raw text/audio, signed URLs, object keys, credentials, or workspace/user identifiers in this document.
