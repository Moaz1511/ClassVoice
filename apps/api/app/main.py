"""FastAPI application factory and process entrypoint."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.v1.api_keys import configure_api_key_state
from .api.v1.api_keys import router as api_keys_router
from .api.v1.generations import router as generations_router
from .api.v1.projects import configure_project_state
from .api.v1.projects import router as projects_router
from .api.v1.reports import configure_moderation_state
from .api.v1.reports import router as reports_router
from .api.v1.voices import configure_upload_state
from .api.v1.voices import router as voices_router
from .api.v1.webhooks import configure_webhook_state
from .api.v1.webhooks import router as webhooks_router
from .core.auth_config import AuthConfigurationError
from .core.errors import (
    APIError,
    api_error_handler,
    envelope,
    http_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from .core.jwt import JWTVerifier
from .core.logging import RequestContextMiddleware, configure_logging
from .core.settings import APISettings
from .domains.audit.service import AuditService, InMemoryAuditEventStore
from .domains.generations.jobs import GenerationService, InMemoryGenerationStore
from .domains.generations.outputs import PrivateGenerationOutputStore
from .inference.adapter import SmokeCpuAdapter
from .inference.model_registry import ModelRegistry
from .storage import build_storage_adapter
from .workers.generation_queue import GenerationWorker, InMemoryGenerationQueue


def create_app(settings: APISettings | None = None) -> FastAPI:
    runtime_settings = settings or APISettings.from_env()
    runtime_settings.validate()
    configure_logging()

    app = FastAPI(
        title=runtime_settings.app_name,
        version=runtime_settings.app_version,
        description="Consent-first academic voice generation control plane.",
        docs_url="/docs" if runtime_settings.app_env != "production" else None,
        redoc_url="/redoc" if runtime_settings.app_env != "production" else None,
    )
    app.state.settings = runtime_settings
    try:
        app.state.jwt_verifier = JWTVerifier.from_config(runtime_settings.auth)
    except AuthConfigurationError:
        app.state.jwt_verifier = None
    app.state.storage_adapter = build_storage_adapter(runtime_settings)
    registry_path = Path(
        os.getenv("MODEL_REGISTRY_PATH", "infra/model-registry/manifest.json")
    )
    app.state.model_registry = (
        ModelRegistry.from_path(registry_path)
        if registry_path.is_file()
        else ModelRegistry.empty()
    )
    app.state.inference_adapter = SmokeCpuAdapter()
    configure_upload_state(app)
    configure_api_key_state(app)
    configure_webhook_state(app)
    configure_moderation_state(app)
    app.state.audit_event_store = InMemoryAuditEventStore()
    app.state.audit_service = AuditService(app.state.audit_event_store)
    configure_project_state(app)
    app.state.generation_store = InMemoryGenerationStore()
    app.state.generation_service = GenerationService(
        app.state.generation_store,
        app.state.voice_service,
        app.state.model_registry,
    )
    app.state.generation_queue = InMemoryGenerationQueue()
    app.state.generation_worker = GenerationWorker(
        app.state.generation_service,
        app.state.generation_queue,
    )
    app.state.generation_outputs = PrivateGenerationOutputStore(app.state.storage_adapter)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "X-API-Key",
            "Content-Type",
            "Idempotency-Key",
            runtime_settings.request_id_header,
        ],
        expose_headers=[runtime_settings.request_id_header],
    )
    app.add_middleware(RequestContextMiddleware, header_name=runtime_settings.request_id_header)
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
    app.include_router(voices_router, prefix="/v1")
    app.include_router(projects_router, prefix="/v1")
    app.include_router(generations_router, prefix="/v1")
    app.include_router(api_keys_router, prefix="/v1")
    app.include_router(webhooks_router, prefix="/v1")
    app.include_router(reports_router, prefix="/v1")

    @app.get("/health/live", tags=["health"])
    async def live(request: Request) -> dict[str, object]:
        return envelope(
            request,
            data={
                "status": "ok",
                "service": runtime_settings.app_name,
                "version": runtime_settings.app_version,
            },
        )

    @app.get("/health/ready", tags=["health"])
    async def ready(request: Request) -> dict[str, object]:
        return envelope(
            request,
            data={
                "status": "ready",
                "service": runtime_settings.app_name,
                "checks": {"configuration": "ok"},
            },
        )

    @app.get("/", include_in_schema=False)
    async def root(request: Request) -> dict[str, object]:
        return envelope(request, data={"service": runtime_settings.app_name})

    return app


app = create_app()
