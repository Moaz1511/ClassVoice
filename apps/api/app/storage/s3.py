"""S3-compatible private storage adapter used by LocalStack and production S3."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.client import Config

from app.core.settings import APISettings

from .ports import (
    ALLOWED_BUCKETS,
    SIGNED_URL_TTL_SECONDS,
    SignedObjectUrl,
    StorageError,
    validate_object_key,
)


class S3StorageAdapter:
    """Generate SigV4 URLs without exposing a public bucket or credentials."""

    def __init__(self, settings: APISettings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client or boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=Config(signature_version="s3v4"),
        )

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
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
        except Exception as error:
            raise StorageError("object upload failed") from error

    async def create_upload_url(
        self,
        bucket: str,
        key: str,
        *,
        content_type: str,
    ) -> SignedObjectUrl:
        bucket, key = self._validate(bucket, key)
        self._validate_content_type(content_type)
        url = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "put_object",
            Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=SIGNED_URL_TTL_SECONDS,
            HttpMethod="PUT",
        )
        return SignedObjectUrl(
            url=url,
            bucket=bucket,
            key=key,
            method="PUT",
            expires_at=datetime.now(UTC) + timedelta(seconds=SIGNED_URL_TTL_SECONDS),
            headers={"Content-Type": content_type},
        )

    async def create_download_url(self, bucket: str, key: str) -> SignedObjectUrl:
        bucket, key = self._validate(bucket, key)
        url = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=SIGNED_URL_TTL_SECONDS,
            HttpMethod="GET",
        )
        return SignedObjectUrl(
            url=url,
            bucket=bucket,
            key=key,
            method="GET",
            expires_at=datetime.now(UTC) + timedelta(seconds=SIGNED_URL_TTL_SECONDS),
            headers={},
        )

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
