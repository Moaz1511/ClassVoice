from __future__ import annotations

from uuid import UUID

import pytest
from app.inference.adapter import (
    InferenceError,
    InferenceRequest,
    deterministic_wav_for_request,
)
from app.inference.model_registry import ModelManifest, ModelManifestEntry, ModelRegistry
from app.inference.openvoice import OpenVoiceV2Adapter, SmokeOpenVoiceRuntime

pytestmark = pytest.mark.asyncio

MODEL_SHA = "a" * 64
REQUEST = InferenceRequest(
    job_id=UUID("00000000-0000-0000-0000-000000000001"),
    input_text="A consented lesson.",
    language_code="en-US",
    output_format="wav",
    speed=1.0,
    stability=0.5,
    style=0.2,
    seed=7,
    model_key="openvoice-v2",
    model_version="2.0.0",
    checkpoint_sha256=MODEL_SHA,
    model_metadata={},
)


def registry() -> ModelRegistry:
    return ModelRegistry(
        ModelManifest(
            1,
            (
                ModelManifestEntry(
                    model_key="openvoice-v2",
                    version="2.0.0",
                    checkpoint_sha256=MODEL_SHA,
                    checkpoint_path="openvoice-v2.pth",
                    runtime="openvoice",
                    license_name="Reviewed license",
                    license_url="https://example.test/license",
                    license_review_status="approved",
                    supported_languages=("en-US",),
                    config={"sample_rate_hz": 24000},
                    enabled=True,
                ),
            ),
        )
    )


async def test_openvoice_adapter_records_device_provenance_and_settings() -> None:
    async def factory(entry: ModelManifestEntry, device: str) -> SmokeOpenVoiceRuntime:
        assert entry.checkpoint_sha256 == MODEL_SHA
        assert device == "cuda"
        return SmokeOpenVoiceRuntime(deterministic_wav_for_request)

    adapter = OpenVoiceV2Adapter(registry(), factory, device="cuda")
    result = await adapter.generate(REQUEST)

    assert result.audio_bytes.startswith(b"RIFF")
    assert result.metadata["adapter"] == "openvoice-v2"
    assert result.metadata["device"] == "cuda"
    assert result.metadata["checkpoint_sha256"] == MODEL_SHA
    assert result.metadata["settings"] == {
        "speed": 1.0,
        "stability": 0.5,
        "style": 0.2,
        "seed": 7,
    }


async def test_openvoice_adapter_fails_closed_for_unknown_checkpoint() -> None:
    async def factory(entry: ModelManifestEntry, device: str) -> SmokeOpenVoiceRuntime:
        return SmokeOpenVoiceRuntime(deterministic_wav_for_request)

    adapter = OpenVoiceV2Adapter(registry(), factory)
    with pytest.raises(InferenceError) as error:
        await adapter.generate(
            InferenceRequest(
                **{
                    "job_id": REQUEST.job_id,
                    "input_text": REQUEST.input_text,
                    "language_code": REQUEST.language_code,
                    "output_format": REQUEST.output_format,
                    "speed": REQUEST.speed,
                    "stability": REQUEST.stability,
                    "style": REQUEST.style,
                    "seed": REQUEST.seed,
                    "model_key": REQUEST.model_key,
                    "model_version": REQUEST.model_version,
                    "checkpoint_sha256": "b" * 64,
                    "model_metadata": {},
                }
            )
        )
    assert error.value.code == "MODEL_NOT_ALLOWLISTED"
