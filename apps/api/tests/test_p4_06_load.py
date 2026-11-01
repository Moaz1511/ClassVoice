from __future__ import annotations

import json

import pytest
from benchmarks.p4_06_load import MAX_TEXT, percentile, run_profile
from benchmarks.p4_06_openvoice_gpu import synthetic_text


def test_percentile_uses_nearest_rank_and_rejects_invalid_samples() -> None:
    assert percentile((1.0, 2.0, 3.0, 4.0), 0.50) == 2.0
    assert percentile((1.0, 2.0, 3.0, 4.0), 0.95) == 4.0
    with pytest.raises(ValueError):
        percentile((), 0.95)
    with pytest.raises(ValueError):
        percentile((1.0,), 0.0)


def test_gpu_benchmark_uses_exact_synthetic_text_boundary() -> None:
    text = synthetic_text(10_000)
    assert len(text) == 10_000
    assert text.startswith("Academic practice")
    with pytest.raises(ValueError):
        synthetic_text(10_001)


async def test_small_load_profile_is_redacted_and_enforces_queue_integrity() -> None:
    report = await run_profile(
        read_requests=8,
        signed_url_requests=4,
        queue_jobs=4,
        concurrency=2,
    )

    assert report["control_plane_status"] == "pass"
    assert report["gpu_status"] == "requires-separate-reference-gpu-run"
    assert report["results"]["api_reads"]["failures"] == 0
    assert report["results"]["signed_urls"]["failures"] == 0
    assert report["results"]["maximum_text_acceptance"]["failures"] == 0
    queue = report["results"]["queue_concurrency"]
    assert queue["terminal_successes"] == 4
    assert queue["output_writes"] == 4
    assert queue["observed_max_concurrency"] == 2
    serialized = json.dumps(report)
    assert MAX_TEXT not in serialized
    assert "object_key" not in serialized
    assert "X-Amz-Signature" not in serialized
