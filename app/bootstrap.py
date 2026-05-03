from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api import install_error_handlers
from app.config import Settings
from app.middleware import (
    create_api_key_auth_middleware,
    create_logging_middleware,
    create_quota_middleware,
    create_rate_limit_middleware,
)
from app.routers.admin import router as admin_router
from app.routers.chat import router as chat_router
from app.routers.health import router as health_router
from app.runtime import AppRuntime
from app.services.admin import ensure_admin_key


def create_runtime(settings: Settings | None = None) -> AppRuntime:
    return AppRuntime(settings=settings or Settings.from_env())


def create_app(runtime: AppRuntime | None = None, settings: Settings | None = None) -> FastAPI:
    runtime = runtime or create_runtime(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = runtime
        created_redis = False
        if runtime.redis_client is None:
            runtime.redis_client = Redis.from_url(runtime.settings.redis_url, decode_responses=True)
            created_redis = True
        runtime.logger.info(
            json.dumps(
                {
                    "message": "startup",
                    "environment": runtime.settings.environment,
                    "provider_mode": runtime.settings.provider_mode,
                },
                separators=(",", ":"),
            )
        )
        ensure_admin_key(runtime)
        try:
            yield
        finally:
            if created_redis and runtime.redis_client is not None:
                await runtime.redis_client.aclose()
                runtime.redis_client = None

    app = FastAPI(
        title="llm-gateway",
        version="1.0.0",
        lifespan=lifespan,
        responses={
            401: {"description": "Unauthorized"},
            403: {"description": "Forbidden"},
            429: {"description": "Rate limited or quota exceeded"},
        },
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime.settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(create_logging_middleware(runtime))
    app.middleware("http")(create_quota_middleware(runtime))
    app.middleware("http")(create_rate_limit_middleware(runtime))
    app.middleware("http")(create_api_key_auth_middleware(runtime))
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(admin_router)
    install_error_handlers(app)
    return app
