from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from app.inference.model_registry import (
    AllowlistedCheckpointLoader,
    ModelRegistry,
    ModelRegistryError,
    load_manifest,
)


def write_manifest(path: Path, **overrides: object) -> str:
    checkpoint_sha = str(overrides.pop("checkpoint_sha256", "a" * 64))
    entry: dict[str, object] = {
        "model_key": "openvoice-v2",
        "version": "2.0.0",
        "checkpoint_sha256": checkpoint_sha,
        "checkpoint_path": "openvoice-v2/checkpoint.bin",
        "runtime": "cpu",
        "license_name": "Reviewed model license",
        "license_url": "https://example.test/license",
        "license_review_status": "approved",
        "supported_languages": ["en-US"],
        "config": {"sample_rate_hz": 24000},
        "enabled": True,
    }
    entry.update(overrides)
    path.write_text(json.dumps({"schema_version": 1, "models": [entry]}), encoding="utf-8")
    return checkpoint_sha


def test_repository_manifest_registers_reviewed_openvoice_checkpoint() -> None:
    manifest = load_manifest(Path("infra/model-registry/manifest.json"))
    assert manifest.schema_version == 1
    assert len(manifest.models) == 1
    entry = manifest.models[0]
    assert entry.model_key == "openvoice-v2"
    assert entry.checkpoint_sha256 == (
        "9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e"
    )
    assert entry.license_review_status == "approved"
    assert entry.enabled is False


def test_allowlisted_loader_verifies_sha_and_returns_immutable_metadata(tmp_path: Path) -> None:
    checkpoint = tmp_path / "openvoice-v2" / "checkpoint.bin"
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"deterministic checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    write_manifest(manifest_path, checkpoint_sha256=digest)

    registry = ModelRegistry.from_path(manifest_path)
    loaded = AllowlistedCheckpointLoader(registry, tmp_path).load(
        "openvoice-v2",
        "2.0.0",
        digest,
        lambda path, entry: {"path": path.name, "metadata": entry.job_metadata()},
    )

    assert loaded["path"] == "checkpoint.bin"  # type: ignore[index]
    assert loaded["metadata"]["checkpoint_sha256"] == digest  # type: ignore[index]


def test_registry_rejects_unknown_license_and_checkpoint_hash(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    digest = write_manifest(manifest_path, license_review_status="pending", enabled=False)
    registry = ModelRegistry.from_path(manifest_path)

    with pytest.raises(ModelRegistryError) as license_error:
        registry.resolve("openvoice-v2", "2.0.0", digest)
    assert license_error.value.code == "MODEL_LICENSE_NOT_APPROVED"

    write_manifest(manifest_path, checkpoint_sha256="b" * 64)
    registry = ModelRegistry.from_path(manifest_path)
    with pytest.raises(ModelRegistryError) as unknown_error:
        registry.resolve("openvoice-v2", "2.0.0", "c" * 64)
    assert unknown_error.value.code == "MODEL_NOT_ALLOWLISTED"


def test_loader_rejects_hash_mismatch_and_path_escape(tmp_path: Path) -> None:
    checkpoint = tmp_path / "openvoice-v2" / "checkpoint.bin"
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"actual checkpoint")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(manifest_path, checkpoint_sha256="d" * 64)
    registry = ModelRegistry.from_path(manifest_path)

    loader = AllowlistedCheckpointLoader(registry, tmp_path)
    with pytest.raises(ModelRegistryError) as hash_error:
        loader.load("openvoice-v2", "2.0.0", "d" * 64, lambda path, entry: path)
    assert hash_error.value.code == "MODEL_CHECKPOINT_HASH_MISMATCH"

    escaped_manifest = tmp_path / "escaped.json"
    write_manifest(
        escaped_manifest,
        checkpoint_sha256="e" * 64,
        checkpoint_path="../outside.bin",
    )
    escaped_registry = ModelRegistry.from_path(escaped_manifest)
    with pytest.raises(ModelRegistryError) as path_error:
        AllowlistedCheckpointLoader(escaped_registry, tmp_path).load(
            "openvoice-v2", "2.0.0", "e" * 64, lambda path, entry: path
        )
    assert path_error.value.code == "MODEL_CHECKPOINT_UNAVAILABLE"


def test_enabled_model_must_have_approved_license(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    write_manifest(path, enabled=True, license_review_status="rejected")
    with pytest.raises(ModelRegistryError) as error:
        load_manifest(path)
    assert error.value.code == "MODEL_MANIFEST_INVALID"
