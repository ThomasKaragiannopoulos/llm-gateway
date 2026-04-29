import json
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis

from app.bootstrap import ensure_admin_key
from app.config import settings
from app.metrics import (
    PROVIDER_CIRCUIT_OPEN_TOTAL,
    PROVIDER_ERRORS_TOTAL,
    PROVIDER_RETRIES_TOTAL,
)
from app.middleware import register_middleware
from app.otel import setup_tracing
from app.routers import admin as admin_router
from app.routers import chat as chat_router
from app.routers import health as health_router
from app.runtime import configure_runtime, initialize_runtime, set_session_factory, state


logger = logging.getLogger("llm-gateway")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.propagate = False


def _provider_error(provider_name: str, stage: str, exc: Exception) -> None:
    PROVIDER_ERRORS_TOTAL.labels(provider_name, stage, exc.__class__.__name__).inc()


def _provider_retry(provider_name: str, stage: str, attempt: int) -> None:
    PROVIDER_RETRIES_TOTAL.labels(provider_name, stage).inc()


def _provider_circuit_open(provider_name: str) -> None:
    PROVIDER_CIRCUIT_OPEN_TOTAL.labels(provider_name).inc()


initialize_runtime(
    on_error=_provider_error,
    on_retry=_provider_retry,
    on_circuit_open=_provider_circuit_open,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
    except Exception:
        logger.warning(
            json.dumps({"message": "redis_unavailable_running_without_cache_and_rate_limits"})
        )
        redis_client = None
    configure_runtime(redis_client=redis_client)
    ensure_admin_key()
    try:
        yield
    finally:
        if state.redis_client is not None:
            await state.redis_client.close()
            configure_runtime(redis_client=None)


def create_app() -> FastAPI:
    app = FastAPI(title="llm-gateway", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-provider", "x-route-reason", "x-cache"],
    )
    setup_tracing(app)

    frontend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
    if os.path.isdir(frontend_root):
        app.mount("/static", StaticFiles(directory=frontend_root, html=False), name="frontend-static")

    app.include_router(health_router.router)
    app.include_router(chat_router.router)
    app.include_router(admin_router.router)
    register_middleware(app)
    return app


def override_runtime_for_tests(*, session_factory=None, redis_client=None, providers=None, health_tracker=None, routing_policy=None):
    if session_factory is not None:
        set_session_factory(session_factory)
    configure_runtime(
        redis_client=redis_client,
        providers=providers,
        health_tracker=health_tracker,
        routing_policy=routing_policy,
    )


app = create_app()
