import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from sqlalchemy import func

from app import state
from app.auth import hash_api_key
from app.db.base import Base
from app.db.models import ApiKey, Tenant, UsageEvent
from app.db.session import engine, get_session
from app.metrics import (
    PROVIDER_CIRCUIT_OPEN_TOTAL,
    PROVIDER_ERRORS_TOTAL,
    PROVIDER_RETRIES_TOTAL,
    QUOTA_DENIED_TOTAL,
    RATE_LIMITED_TOTAL,
    REQUEST_LATENCY,
    REQUESTS_TOTAL,
)
from app.mock_provider import MockProvider
from app.ollama_provider import OllamaProvider
from app.reliability import CircuitBreaker, ResilientProvider, RetryConfig
from app.routing import ProviderHealth, RoutingPolicy
from app.otel import setup_tracing
from app.routers import admin as admin_router
from app.routers import chat as chat_router
from app.routers import health as health_router

logger = logging.getLogger("llm-gateway")
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_handler)
logger.propagate = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REQUESTS_PER_MINUTE = int(os.getenv("REQUESTS_PER_MINUTE", "60"))
TOKENS_PER_MINUTE = int(os.getenv("TOKENS_PER_MINUTE", "1000"))

PROVIDER_MODE = os.getenv("PROVIDER_MODE", "mock")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
PRIMARY_FAIL_RATE = float(os.getenv("PRIMARY_FAIL_RATE", "0"))
FALLBACK_FAIL_RATE = float(os.getenv("FALLBACK_FAIL_RATE", "0"))
PROVIDER_RETRIES = int(os.getenv("PROVIDER_RETRIES", "2"))
PROVIDER_RETRY_BASE_MS = int(os.getenv("PROVIDER_RETRY_BASE_MS", "200"))
PROVIDER_RETRY_MAX_MS = int(os.getenv("PROVIDER_RETRY_MAX_MS", "2000"))
CIRCUIT_FAILURE_THRESHOLD = int(os.getenv("CIRCUIT_FAILURE_THRESHOLD", "5"))
CIRCUIT_RESET_SECONDS = int(os.getenv("CIRCUIT_RESET_SECONDS", "30"))
HEALTH_MIN_SAMPLES = int(os.getenv("HEALTH_MIN_SAMPLES", "5"))
HEALTH_ERROR_THRESHOLD = float(os.getenv("HEALTH_ERROR_THRESHOLD", "0.5"))

# ---------------------------------------------------------------------------
# Provider setup
# ---------------------------------------------------------------------------

def _provider_error(provider_name: str, stage: str, exc: Exception) -> None:
    PROVIDER_ERRORS_TOTAL.labels(provider_name, stage, exc.__class__.__name__).inc()


def _provider_retry(provider_name: str, stage: str, attempt: int) -> None:
    PROVIDER_RETRIES_TOTAL.labels(provider_name, stage).inc()


def _provider_circuit_open(provider_name: str) -> None:
    PROVIDER_CIRCUIT_OPEN_TOTAL.labels(provider_name).inc()


_retry_config = RetryConfig(
    max_attempts=PROVIDER_RETRIES,
    base_delay_ms=PROVIDER_RETRY_BASE_MS,
    max_delay_ms=PROVIDER_RETRY_MAX_MS,
)


def _wrap_provider(name: str, provider):
    breaker = CircuitBreaker(
        failure_threshold=CIRCUIT_FAILURE_THRESHOLD,
        reset_timeout_s=CIRCUIT_RESET_SECONDS,
    )
    return ResilientProvider(
        provider,
        name=name,
        retry=_retry_config,
        circuit_breaker=breaker,
        on_error=_provider_error,
        on_retry=_provider_retry,
        on_circuit_open=_provider_circuit_open,
    )


if PROVIDER_MODE == "ollama":
    _base_providers = {
        "primary": OllamaProvider(base_url=OLLAMA_URL),
        "fallback": MockProvider(delay_ms=100, fail_rate=FALLBACK_FAIL_RATE),
    }
else:
    _base_providers = {
        "primary": MockProvider(delay_ms=200, fail_rate=PRIMARY_FAIL_RATE),
        "fallback": MockProvider(delay_ms=100, fail_rate=FALLBACK_FAIL_RATE),
    }

state.providers = {name: _wrap_provider(name, p) for name, p in _base_providers.items()}
state.health_tracker = ProviderHealth(window_size=50, min_samples=HEALTH_MIN_SAMPLES)
state.routing_policy = RoutingPolicy(error_rate_threshold=HEALTH_ERROR_THRESHOLD)

# ---------------------------------------------------------------------------
# Admin bootstrap
# ---------------------------------------------------------------------------

def _ensure_admin_key():
    admin_key = os.getenv("ADMIN_API_KEY")
    if not admin_key:
        logger.warning(json.dumps({"message": "admin_key_missing"}))
        return

    db = get_session()
    try:
        admin_tenant = db.query(Tenant).filter(Tenant.name == "admin").one_or_none()
        if admin_tenant is None:
            admin_tenant = Tenant(name="admin")
            db.add(admin_tenant)
            db.commit()
            db.refresh(admin_tenant)

        key_hash = hash_api_key(admin_key)
        existing = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).one_or_none()
        if existing is None:
            named = (
                db.query(ApiKey)
                .filter(ApiKey.tenant_id == admin_tenant.id, ApiKey.name == "admin-env")
                .one_or_none()
            )
            active_admin_keys = (
                db.query(ApiKey)
                .filter(ApiKey.tenant_id == admin_tenant.id, ApiKey.active.is_(True))
                .count()
            )
            if named is None:
                db.add(
                    ApiKey(
                        tenant_id=admin_tenant.id,
                        name="admin-env",
                        key_hash=key_hash,
                        active=True,
                    )
                )
                db.commit()
            else:
                if active_admin_keys > 0 and named.key_hash != key_hash:
                    logger.warning(json.dumps({"message": "admin_key_env_mismatch"}))
                else:
                    named.key_hash = key_hash
                    named.active = True
                    db.add(named)
                    db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    try:
        state.redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
        await state.redis_client.ping()
    except Exception:
        logger.warning(json.dumps({"message": "redis_unavailable_running_without_cache_and_rate_limits"}))
        state.redis_client = None
    _ensure_admin_key()
    try:
        yield
    finally:
        if state.redis_client is not None:
            await state.redis_client.close()
            state.redis_client = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="llm-gateway", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-provider", "x-route-reason", "x-cache"],
)
setup_tracing(app)

_frontend_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend")
)
if os.path.isdir(_frontend_root):
    app.mount("/static", StaticFiles(directory=_frontend_root, html=False), name="frontend-static")

app.include_router(health_router.router)
app.include_router(chat_router.router)
app.include_router(admin_router.router)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

_PUBLIC_PATHS = {
    "/health", "/metrics",
    "/health/ollama", "/health/grafana", "/health/prometheus",
}
_FRONTEND_PATHS = {"/", "/tenants", "/keys", "/chat"}


def _resolve_tenant_id(request: Request):
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is not None:
        return tenant_id

    raw_key = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        raw_key = auth_header.split(" ", 1)[1].strip()
    if not raw_key:
        raw_key = request.headers.get("X-API-Key")
    if not raw_key:
        return None

    db = get_session()
    try:
        api_key_row = (
            db.query(ApiKey.tenant_id)
            .filter(ApiKey.key_hash == hash_api_key(raw_key), ApiKey.active.is_(True))
            .one_or_none()
        )
        if api_key_row is None:
            return None
        request.state.tenant_id = api_key_row.tenant_id
        return api_key_row.tenant_id
    finally:
        db.close()


@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path in _PUBLIC_PATHS:
        return await call_next(request)
    if request.url.path in _FRONTEND_PATHS or request.url.path.startswith("/static"):
        return await call_next(request)

    raw_key = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        raw_key = auth_header.split(" ", 1)[1].strip()
    if not raw_key:
        raw_key = request.headers.get("X-API-Key")

    if not raw_key:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "unauthorized", "message": "Missing API key"}},
        )

    key_hash = hash_api_key(raw_key)
    db = get_session()
    try:
        api_key_row = (
            db.query(ApiKey.id, ApiKey.tenant_id)
            .filter(ApiKey.key_hash == key_hash, ApiKey.active.is_(True))
            .one_or_none()
        )
        if api_key_row is not None:
            db.query(ApiKey).filter(ApiKey.id == api_key_row.id).update(
                {"last_used_at": func.now()}
            )
            db.commit()
    finally:
        db.close()

    if api_key_row is None:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "unauthorized", "message": "Invalid API key"}},
        )

    request.state.tenant_id = api_key_row.tenant_id
    return await call_next(request)


@app.middleware("http")
async def rate_limit_requests(request: Request, call_next):
    if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/v1/admin"):
        return await call_next(request)
    if state.redis_client is None:
        return await call_next(request)

    tenant_id = _resolve_tenant_id(request) or "unknown"
    minute_bucket = int(time.time() // 60)
    key = f"rl:req:{tenant_id}:{minute_bucket}"

    count = await state.redis_client.incr(key)
    if count == 1:
        await state.redis_client.expire(key, 60)

    if count > REQUESTS_PER_MINUTE:
        retry_after = 60 - int(time.time() % 60)
        RATE_LIMITED_TOTAL.labels("requests_per_minute").inc()
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"error": {"code": "rate_limited", "message": "Request limit exceeded"}},
        )

    token_estimate = 2
    token_key = f"rl:tokens:{tenant_id}:{minute_bucket}"
    token_count = await state.redis_client.incrby(token_key, token_estimate)
    if token_count == token_estimate:
        await state.redis_client.expire(token_key, 60)

    if token_count > TOKENS_PER_MINUTE:
        retry_after = 60 - int(time.time() % 60)
        RATE_LIMITED_TOTAL.labels("tokens_per_minute").inc()
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"error": {"code": "rate_limited", "message": "Token limit exceeded"}},
        )

    return await call_next(request)


@app.middleware("http")
async def quota_limits(request: Request, call_next):
    if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/v1/admin"):
        return await call_next(request)

    tenant_id = _resolve_tenant_id(request)
    if tenant_id is None:
        return await call_next(request)

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).one_or_none()
        if tenant is None:
            return await call_next(request)
        if tenant.token_limit_per_day is None and tenant.spend_limit_per_day_usd is None:
            return await call_next(request)

        today = func.date(func.now())
        totals = (
            db.query(
                func.coalesce(func.sum(UsageEvent.tokens), 0),
                func.coalesce(func.sum(UsageEvent.cost_usd), 0.0),
            )
            .filter(UsageEvent.tenant_id == tenant.id)
            .filter(func.date(UsageEvent.created_at) == today)
            .one()
        )
        tokens_used = int(totals[0] or 0)
        cost_used = float(totals[1] or 0.0)

        warn_headers = {}
        if tenant.token_limit_per_day:
            remaining_tokens = tenant.token_limit_per_day - tokens_used
            warn_headers["X-RateLimit-Tokens-Remaining"] = str(max(remaining_tokens, 0))
            if remaining_tokens <= 0:
                QUOTA_DENIED_TOTAL.labels("token_limit").inc()
                return JSONResponse(
                    status_code=429,
                    headers=warn_headers,
                    content={"error": {"code": "quota_exceeded", "message": "Daily token budget exceeded"}},
                )

        if tenant.spend_limit_per_day_usd:
            remaining_spend = tenant.spend_limit_per_day_usd - cost_used
            warn_headers["X-RateLimit-Spend-Remaining"] = f"{max(remaining_spend, 0):.6f}"
            if remaining_spend <= 0:
                QUOTA_DENIED_TOTAL.labels("spend_limit").inc()
                return JSONResponse(
                    status_code=429,
                    headers=warn_headers,
                    content={"error": {"code": "quota_exceeded", "message": "Daily spend budget exceeded"}},
                )

        response = await call_next(request)
        for k, v in warn_headers.items():
            response.headers[k] = v
        return response
    finally:
        db.close()


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    start = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
    finally:
        elapsed_seconds = time.perf_counter() - start
        logger.info(
            json.dumps(
                {
                    "message": "request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": getattr(response, "status_code", None),
                    "duration_ms": round(elapsed_seconds * 1000, 2),
                    "idempotency_key": idempotency_key,
                },
                separators=(",", ":"),
            )
        )

    if response is None:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Unhandled error"}},
        )

    response.headers["X-Request-Id"] = request_id
    if idempotency_key:
        response.headers["Idempotency-Key"] = idempotency_key

    status_code = str(getattr(response, "status_code", 500))
    REQUESTS_TOTAL.labels(request.method, request.url.path, status_code).inc()
    REQUEST_LATENCY.labels(request.method, request.url.path).observe(elapsed_seconds)
    return response
