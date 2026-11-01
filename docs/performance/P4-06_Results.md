# P4-06 Load and Reference-GPU Results

**Measured:** 2026-11-01  
**Status:** Control-plane pass; maximum-text GPU known gap  
**Reference GPU:** NVIDIA GeForce GTX 1660 Ti, 6 GB  
**Model:** OpenVoice V2 `2.0.0`, checkpoint SHA-256
`9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e`

## Result summary

The authenticated API, real local SigV4 signing path, maximum-text request
acceptance, and bounded queue concurrency profile pass their local targets. A
real OpenVoice CUDA probe also succeeds on the reference GPU.

The required 10,000-character OpenVoice workload does **not** meet the launch
target: it exceeded the 180-second hard benchmark timeout and therefore also
missed the PRD's 90-second queue-to-complete target. This is recorded as a
known gap, not a pass. The process was terminated by the parent and released
its CUDA allocation cleanly.

## Control-plane profile

Environment: Python `3.13.14`, FastAPI/HTTPX ASGI transport, real boto3 SigV4
URL generation, synthetic private object writes, and a bounded asynchronous
inference stand-in. Concurrency was `4`.

| Scenario | Workload | P95 | Target | Result |
|---|---:|---:|---:|---|
| Authenticated generation reads | 200 requests | 4.951 ms | < 400 ms | Pass |
| Authorized signed-download reads | 100 requests | 35.984 ms | < 400 ms | Pass |
| 10,000-character generation acceptance | 24 requests | 6.499 ms | < 400 ms operational guardrail | Pass |
| Queue-to-complete smoke proxy | 24 jobs / 4 workers | 153.528 ms | < 90,000 ms | Pass (synthetic only) |

Queue integrity evidence:

- configured concurrency: `4`;
- observed maximum concurrency: `4`;
- unique terminal successes: `24/24`;
- private output writes: `24/24`;
- duplicate outputs: `0`;
- control-plane throughput: `185.338` jobs/second for the bounded stand-in.

These ASGI measurements exclude network, reverse-proxy, SQL, and Redis
latency. They prove the application boundaries and concurrency invariants, not
hosted end-to-end capacity. The pilot environment must repeat the profile over
its deployed network and durable repositories.

## OpenVoice reference-GPU profile

Runtime: Python `3.11.5`, PyTorch `2.7.1+cu126`, torchaudio
`2.7.1+cu126`, CUDA runtime `12.6`, host driver `616.92`. Model downloads were
disabled; the benchmark used only the already provisioned, SHA-verified local
checkpoint and cached base models. The production registry entry remains
disabled.

### Short capability probe

| Metric | Measured |
|---|---:|
| Synthetic input | 128 characters |
| Model/runtime load | 17,211.001 ms |
| Inference and conversion | 12,743.668 ms |
| Generated duration | 7,721 ms |
| Output size | 340,524 bytes |
| Peak allocated GPU memory | 1,136,464,384 bytes |
| Output | Mono, 16-bit, 22,050 Hz WAV |

The probe proves that OpenVoice V2 executes correctly on the GTX 1660 Ti. It
is one observation and is not presented as a statistical P95.

### Maximum-text workload

| Metric | Measured |
|---|---:|
| Synthetic input | 10,000 characters |
| Required target | < 90,000 ms |
| Hard safety timeout | 180,000 ms |
| Outcome | Timed out; known gap |
| User/private data used | None |

The short probe produced 7.7 seconds of speech from 128 characters. A single
10,000-character output is therefore also structurally at risk of exceeding
the product's 120-second/25 MB output limits. Resolving this requires an ADR:
either segment long academic text into multiple bounded audio outputs with
project-level playback/export semantics, or lower the per-job character limit.
The current code must not claim the 10,000-character GPU SLA during pilot.

## Reproduction

From an API environment with the locked runtime dependencies:

```powershell
Set-Location apps/api
python -m benchmarks.p4_06_load `
  --read-requests 200 `
  --signed-url-requests 100 `
  --queue-jobs 24 `
  --concurrency 4
```

From the repository root after provisioning the separate CUDA environment:

```powershell
private\openvoice-runtime\.venv-gpu\Scripts\python.exe `
  apps/api/benchmarks/p4_06_openvoice_gpu.py `
  --characters 10000 `
  --timeout-seconds 180 `
  --json-output private/openvoice-runtime/outputs/p4-06-gpu-max-text.json
```

The JSON output path is intentionally under ignored `private/`. Reports and
logs contain no source text, audio bytes, credentials, signed URLs, object
keys, embeddings, or user/workspace identifiers.
