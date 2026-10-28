"""Storage adapter factory."""

from app.core.settings import APISettings

from .ports import StorageAdapter, StorageError
from .s3 import S3StorageAdapter
from .supabase import SupabaseStorageAdapter


def build_storage_adapter(settings: APISettings) -> StorageAdapter:
    if settings.storage_provider == "s3":
        return S3StorageAdapter(settings)
    if settings.storage_provider == "supabase":
        return SupabaseStorageAdapter(settings)
    raise StorageError(f"unsupported storage provider: {settings.storage_provider}")
