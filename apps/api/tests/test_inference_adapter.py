from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest
from app.inference.adapter import InferenceError, InferenceRequest, SmokeCpuAdapter

pytestmark = pytest.mark.asyncio

REQUEST = InferenceRequest(
    job_id=UUID("00000000-0000-0000-0000-000000000001"),
    input_text="A deterministic lesson.",
    language_code="en-US",
    output_format="wav",
    speed=1.0,
    stability=0.5,
    style=0.2,
    seed=7,
    model_key="openvoice-v2",
    model_version="2.0.0",
    checkpoint_sha256="a" * 64,
    model_metadata={"runtime": "cpu"},
)


async def test_smoke_adapter_is_deterministic_and_emits_valid_wav() -> None:
    adapter = SmokeCpuAdapter()
    first = await adapter.generate(REQUEST)
    second = await adapter.generate(REQUEST)

    assert first.audio_bytes == second.audio_bytes
    assert first.sha256 == second.sha256
    assert first.audio_bytes.startswith(b"RIFF")
    assert first.content_type == "audio/wav"
    assert first.sample_rate_hz == 24_000
    assert first.channels == 1
    assert first.duration_ms == 500
    assert first.metadata["deterministic"] is True


async def test_smoke_adapter_rejects_unsupported_format_and_oversized_text() -> None:
    adapter = SmokeCpuAdapter()
    with pytest.raises(InferenceError) as format_error:
        await adapter.generate(replace(REQUEST, output_format="mp3"))
    assert format_error.value.code == "INFERENCE_FORMAT_UNSUPPORTED"

    with pytest.raises(InferenceError) as text_error:
        await adapter.generate(replace(REQUEST, input_text="x" * 10_001))
    assert text_error.value.code == "INFERENCE_INPUT_INVALID"
