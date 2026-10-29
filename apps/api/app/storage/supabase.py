"""Supabase Storage adapter using server-only signed URL endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.core.settings import APISettings

from .ports import (
    ALLOWED_BUCKETS,
    SIGNED_URL_TTL_SECONDS,
    SignedObjectUrl,
    StorageError,
    validate_object_key,
)


class SupabaseStorageAdapter:
    """Mint signed upload/download URLs through the private Storage REST API."""

    def __init__(self, settings: APISettings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._base_url = f"{settings.supabase_url}/storage/v1"
        self._client = client or httpx.AsyncClient(timeout=15.0)
        self._owns_client = client is None

    async def put_object(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str,
    ) -> None:
        bucket, key = self._validate(bucket, key)
        self._validate_content_type(content_type)
        if not body:
            raise StorageError("object body is empty")
        try:
            response = await self._client.request(
                "POST",
                f"{self._base_url}/object/{quote(bucket, safe='')}/{quote(key, safe='/')}",
                headers={
                    "Authorization": f"Bearer {self._settings.supabase_service_role_key}",
                    "apikey": self._settings.supabase_service_role_key,
                    "Content-Type": content_type,
                    # The object key is content-addressed, so retrying a
                    # crashed worker is idempotent and safe to overwrite.
                    "x-upsert": "true",
                },
                content=body,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise StorageError("Supabase object upload failed") from error

    async def create_upload_url(
        self,
        bucket: str,
        key: str,
        *,
        content_type: str,
    ) -> SignedObjectUrl:
        bucket, key = self._validate(bucket, key)
        self._validate_content_type(content_type)
        response = await self._request(
            "POST",
            f"/object/upload/sign/{quote(bucket, safe='')}/{quote(key, safe='/')}?upsert=false",
        )
        signed_url = response.get("url")
        if not isinstance(signed_url, str) or not signed_url:
            raise StorageError("Supabase did not return a signed upload URL")
        return SignedObjectUrl(
            url=self._absolute_url(signed_url),
            bucket=bucket,
            key=key,
            method="PUT",
            expires_at=datetime.now(UTC) + timedelta(seconds=SIGNED_URL_TTL_SECONDS),
            headers={"Content-Type": content_type},
        )

    async def create_download_url(self, bucket: str, key: str) -> SignedObjectUrl:
        bucket, key = self._validate(bucket, key)
        response = await self._request(
            "POST",
            f"/object/sign/{quote(bucket, safe='')}/{quote(key, safe='/')}",
            json={"expiresIn": SIGNED_URL_TTL_SECONDS},
        )
        signed_url = response.get("signedURL")
        if not isinstance(signed_url, str) or not signed_url:
            raise StorageError("Supabase did not return a signed download URL")
        return SignedObjectUrl(
            url=self._absolute_url(signed_url),
            bucket=bucket,
            key=key,
            method="GET",
            expires_at=datetime.now(UTC) + timedelta(seconds=SIGNED_URL_TTL_SECONDS),
            headers={},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self._settings.supabase_service_role_key}",
                    "apikey": self._settings.supabase_service_role_key,
                },
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise StorageError("Supabase Storage request failed") from error
        if not isinstance(payload, dict):
            raise StorageError("Supabase Storage returned an invalid response")
        return payload

    def _absolute_url(self, value: str) -> str:
        if value.startswith("https://"):
            return value
        return f"{self._base_url.rstrip('/')}/{value.lstrip('/')}"

    @staticmethod
    def _validate(bucket: str, key: str) -> tuple[str, str]:
        if bucket not in ALLOWED_BUCKETS:
            raise StorageError("storage bucket is not allowlisted")
        return bucket, validate_object_key(key)

    @staticmethod
    def _validate_content_type(content_type: str) -> None:
        if (
            not content_type
            or len(content_type) > 255
            or "\r" in content_type
            or "\n" in content_type
        ):
            raise StorageError("content type is invalid")
