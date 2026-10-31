"""License-gated, SHA-pinned model registry and checkpoint loader.

This module intentionally has no PyTorch dependency.  It verifies that a
checkpoint is declared in the repository-controlled manifest, has an approved
license, is enabled, remains inside the configured checkpoint root, and matches
the immutable SHA-256 recorded in the manifest before handing the path to a
runtime-specific loader.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

LicenseReviewStatus = Literal["pending", "approved", "rejected"]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_MAX_MANIFEST_BYTES = 1_048_576


class ModelRegistryError(ValueError):
    """A stable, user-safe registry or checkpoint verification error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RuntimeCheckpointLoader(Protocol):
    def __call__(self, path: Path, entry: ModelManifestEntry) -> object: ...


@dataclass(frozen=True, slots=True)
class ModelManifestEntry:
    model_key: str
    version: str
    checkpoint_sha256: str
    checkpoint_path: str
    runtime: str
    license_name: str
    license_url: str | None
    license_review_status: LicenseReviewStatus
    supported_languages: tuple[str, ...]
    config: Mapping[str, object]
    enabled: bool

    def identity(self) -> tuple[str, str, str]:
        return (self.model_key, self.version, self.checkpoint_sha256)

    def job_metadata(self) -> dict[str, object]:
        """Return the immutable provenance copied onto a generation job."""

        return {
            "model_key": self.model_key,
            "version": self.version,
            "checkpoint_sha256": self.checkpoint_sha256,
            "runtime": self.runtime,
            "license_name": self.license_name,
            "license_url": self.license_url,
            "supported_languages": list(self.supported_languages),
            "config": dict(self.config),
        }


@dataclass(frozen=True, slots=True)
class ModelManifest:
    schema_version: int
    models: tuple[ModelManifestEntry, ...]


def load_manifest(path: Path) -> ModelManifest:
    """Load and validate a repository-controlled JSON registry manifest."""

    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ModelRegistryError(
            "MODEL_MANIFEST_UNAVAILABLE", "Model registry manifest is unavailable."
        ) from error
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise ModelRegistryError(
            "MODEL_MANIFEST_TOO_LARGE", "Model registry manifest is too large."
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelRegistryError(
            "MODEL_MANIFEST_INVALID", "Model registry manifest is invalid JSON."
        ) from error
    if not isinstance(payload, dict):
        raise ModelRegistryError(
            "MODEL_MANIFEST_INVALID", "Model registry manifest must be an object."
        )
    schema_version = payload.get("schema_version")
    models = payload.get("models")
    if schema_version != 1 or not isinstance(models, list):
        raise ModelRegistryError(
            "MODEL_MANIFEST_INVALID", "Model registry manifest schema is unsupported."
        )
    entries = tuple(_parse_entry(item) for item in models)
    identities = [entry.identity() for entry in entries]
    if len(set(identities)) != len(identities):
        raise ModelRegistryError(
            "MODEL_MANIFEST_DUPLICATE", "Model registry contains duplicate identities."
        )
    return ModelManifest(schema_version=1, models=entries)


class ModelRegistry:
    def __init__(self, manifest: ModelManifest) -> None:
        self._entries = {entry.identity(): entry for entry in manifest.models}

    @classmethod
    def from_path(cls, path: Path) -> ModelRegistry:
        return cls(load_manifest(path))

    @classmethod
    def empty(cls) -> ModelRegistry:
        return cls(ModelManifest(schema_version=1, models=()))

    def resolve(self, model_key: str, version: str, checkpoint_sha256: str) -> ModelManifestEntry:
        normalized_sha = checkpoint_sha256.strip().lower()
        if not _SHA256_RE.fullmatch(normalized_sha):
            raise ModelRegistryError("MODEL_SHA_INVALID", "Model checkpoint SHA-256 is invalid.")
        entry = self._entries.get((model_key, version, normalized_sha))
        if entry is None:
            raise ModelRegistryError(
                "MODEL_NOT_ALLOWLISTED", "Model checkpoint is not allowlisted."
            )
        if entry.license_review_status != "approved":
            raise ModelRegistryError(
                "MODEL_LICENSE_NOT_APPROVED", "Model license has not been approved."
            )
        if not entry.enabled:
            raise ModelRegistryError("MODEL_DISABLED", "Model is disabled.")
        return entry

    def metadata_for_job(
        self, model_key: str, version: str, checkpoint_sha256: str
    ) -> dict[str, object]:
        return self.resolve(model_key, version, checkpoint_sha256).job_metadata()

    def entries(self) -> tuple[ModelManifestEntry, ...]:
        return tuple(self._entries.values())


class AllowlistedCheckpointLoader:
    """Verify and load a checkpoint without downloading arbitrary paths."""

    def __init__(self, registry: ModelRegistry, checkpoint_root: Path) -> None:
        self._registry = registry
        self._root = checkpoint_root.resolve()

    def load(
        self,
        model_key: str,
        version: str,
        checkpoint_sha256: str,
        runtime_loader: RuntimeCheckpointLoader,
    ) -> object:
        entry = self._registry.resolve(model_key, version, checkpoint_sha256)
        checkpoint_path = (self._root / entry.checkpoint_path).resolve()
        if not _is_within(checkpoint_path, self._root) or not checkpoint_path.is_file():
            raise ModelRegistryError(
                "MODEL_CHECKPOINT_UNAVAILABLE", "Allowlisted checkpoint file is unavailable."
            )
        actual_sha = _sha256_file(checkpoint_path)
        if actual_sha != entry.checkpoint_sha256:
            raise ModelRegistryError(
                "MODEL_CHECKPOINT_HASH_MISMATCH", "Checkpoint SHA-256 does not match the registry."
            )
        return runtime_loader(checkpoint_path, entry)


def _parse_entry(value: object) -> ModelManifestEntry:
    if not isinstance(value, dict):
        raise ModelRegistryError(
            "MODEL_MANIFEST_INVALID", "Each model registry entry must be an object."
        )
    required = (
        "model_key",
        "version",
        "checkpoint_sha256",
        "checkpoint_path",
        "runtime",
        "license_name",
        "license_review_status",
        "supported_languages",
        "config",
        "enabled",
    )
    if any(field not in value for field in required):
        raise ModelRegistryError(
            "MODEL_MANIFEST_INVALID", "Model registry entry is missing required fields."
        )
    model_key = _identifier(value["model_key"], "model_key")
    version = _identifier(value["version"], "version")
    checkpoint_sha256 = value["checkpoint_sha256"]
    checkpoint_path = value["checkpoint_path"]
    runtime = value["runtime"]
    license_name = value["license_name"]
    license_url = value.get("license_url")
    status = value["license_review_status"]
    supported_languages = value["supported_languages"]
    config = value["config"]
    enabled = value["enabled"]
    if not isinstance(checkpoint_sha256, str) or not _SHA256_RE.fullmatch(checkpoint_sha256):
        raise ModelRegistryError(
            "MODEL_MANIFEST_INVALID", "Checkpoint SHA-256 must be lowercase hexadecimal."
        )
    if (
        not isinstance(checkpoint_path, str)
        or not checkpoint_path
        or Path(checkpoint_path).is_absolute()
    ):
        raise ModelRegistryError("MODEL_MANIFEST_INVALID", "Checkpoint path must be relative.")
    if (
        not isinstance(runtime, str)
        or not runtime.strip()
        or not isinstance(license_name, str)
        or not license_name.strip()
    ):
        raise ModelRegistryError("MODEL_MANIFEST_INVALID", "Runtime and license name are required.")
    if license_url is not None and (
        not isinstance(license_url, str) or not license_url.startswith("https://")
    ):
        raise ModelRegistryError("MODEL_MANIFEST_INVALID", "License URL must use HTTPS.")
    if status not in {"pending", "approved", "rejected"}:
        raise ModelRegistryError("MODEL_MANIFEST_INVALID", "License review status is invalid.")
    if not isinstance(supported_languages, list) or not all(
        isinstance(language, str) and language for language in supported_languages
    ):
        raise ModelRegistryError("MODEL_MANIFEST_INVALID", "Supported languages are invalid.")
    if not isinstance(config, dict) or not isinstance(enabled, bool):
        raise ModelRegistryError(
            "MODEL_MANIFEST_INVALID", "Model config or enabled flag is invalid."
        )
    if enabled and status != "approved":
        raise ModelRegistryError("MODEL_MANIFEST_INVALID", "Only approved models may be enabled.")
    return ModelManifestEntry(
        model_key=model_key,
        version=version,
        checkpoint_sha256=checkpoint_sha256,
        checkpoint_path=checkpoint_path,
        runtime=runtime.strip(),
        license_name=license_name.strip(),
        license_url=license_url,
        license_review_status=cast(LicenseReviewStatus, status),
        supported_languages=tuple(supported_languages),
        config=config,
        enabled=enabled,
    )


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ModelRegistryError("MODEL_MANIFEST_INVALID", f"Model {field} is invalid.")
    return value


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ModelRegistryError(
            "MODEL_CHECKPOINT_UNAVAILABLE", "Checkpoint could not be read."
        ) from error
    return digest.hexdigest()
