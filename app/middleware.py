from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import func

from app.auth import hash_api_key
from app.config import settings
from app.db.models import ApiKey, Tenant, UsageEvent
from app.metrics import (
    QUOTA_DENIED_TOTAL,
    RATE_LIMITED_TOTAL,
    REQUEST_LATENCY,
    REQUESTS_TOTAL,
)
from app.runtime import get_session, state


logger = logging.getLogger("llm-gateway")

PUBLIC_PATHS = {
    "/health",
    "/metrics",
    "/health/ollama",
    "/health/grafana",
    "/health/prometheus",
}
FRONTEND_PATHS = {"/", "/tenants", "/keys", "/chat"}


def _extract_api_key(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return request.headers.get("X-API-Key")


def _is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS


def _is_frontend_path(path: str) -> bool:
    return path in FRONTEND_PATHS or path.startswith("/static")


def _bypass_auth(path: str, method: str) -> bool:
    return method == "OPTIONS" or _is_public_path(path) or _is_frontend_path(path)


# ---------------------------------------------------------------------------
# Sync DB helpers — run via asyncio.to_thread to avoid blocking the event loop
# ---------------------------------------------------------------------------

def _db_authenticate(key_hash: str):
    """Returns (api_key_id, tenant_id) row or None. Stamps last_used_at on hit."""
    db = get_session()
    try:
        row = (
            db.query(ApiKey.id, ApiKey.tenant_id)
            .filter(ApiKey.key_hash == key_hash, ApiKey.active.is_(True))
            .one_or_none()
        )
        if row is not None:
            db.query(ApiKey).filter(ApiKey.id == row.id).update(
                {"last_used_at": func.now()}
            )
            db.commit()
        return row
    finally:
        db.close()


def _db_resolve_tenant_id(key_hash: str):
    """Looks up tenant_id for a key hash without stamping last_used_at."""
    db = get_session()
    try:
        row = (
            db.query(ApiKey.tenant_id)
            .filter(ApiKey.key_hash == key_hash, ApiKey.active.is_(True))
            .one_or_none()
        )
        return row.tenant_id if row else None
    finally:
        db.close()


def _db_quota_check(tenant_id):
    """Returns quota info dict or None if tenant has no limits."""
    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).one_or_none()
        if tenant is None:
            return None
        if tenant.token_limit_per_day is None and tenant.spend_limit_per_day_usd is None:
            return None
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
        return {
            "token_limit": tenant.token_limit_per_day,
            "spend_limit": tenant.spend_limit_per_day_usd,
            "tokens_used": int(totals[0] or 0),
            "cost_used": float(totals[1] or 0.0),
        }
    finally:
        db.close()


async def _estimate_request_tokens(request: Request) -> int:
    """Estimates token count from request body messages. Body is cached by Starlette."""
    try:
        body = await request.body()
        data = json.loads(body)
        messages = data.get("messages", [])
        text = " ".join(m.get("content", "") for m in messages if isinstance(m, dict))
        return max(1, len(text) // 4)
    except Exception:
        return 100  # conservative fallback


def register_middleware(app) -> None:
    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):
        if _bypass_auth(request.url.path, request.method):
            return await call_next(request)

        raw_key = _extract_api_key(request)
        if not raw_key:
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "unauthorized", "message": "Missing API key"}},
            )

        key_hash = hash_api_key(raw_key)
        api_key_row = await asyncio.to_thread(_db_authenticate, key_hash)

        if api_key_row is None:
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "unauthorized", "message": "Invalid API key"}},
            )

        request.state.tenant_id = api_key_row.tenant_id
        return await call_next(request)

    @app.middleware("http")
    async def rate_limit_requests(request: Request, call_next):
        if _is_public_path(request.url.path) or request.url.path.startswith("/v1/admin"):
            return await call_next(request)
        if state.redis_client is None:
            return await call_next(request)

        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id is None:
            raw_key = _extract_api_key(request)
            if raw_key:
                tenant_id = await asyncio.to_thread(
                    _db_resolve_tenant_id, hash_api_key(raw_key)
                )
        tenant_key_part = str(tenant_id) if tenant_id else "unknown"
        minute_bucket = int(time.time() // 60)
        key = f"rl:req:{tenant_key_part}:{minute_bucket}"

        count = await state.redis_client.incr(key)
        if count == 1:
            await state.redis_client.expire(key, 60)

        if count > settings.requests_per_minute:
            retry_after = 60 - int(time.time() % 60)
            RATE_LIMITED_TOTAL.labels("requests_per_minute").inc()
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={"error": {"code": "rate_limited", "message": "Request limit exceeded"}},
            )

        estimated_tokens = await _estimate_request_tokens(request)
        token_key = f"rl:tokens:{tenant_key_part}:{minute_bucket}"
        token_count = await state.redis_client.incrby(token_key, estimated_tokens)
        if token_count == estimated_tokens:
            await state.redis_client.expire(token_key, 60)

        if token_count > settings.tokens_per_minute:
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
        if _is_public_path(request.url.path) or request.url.path.startswith("/v1/admin"):
            return await call_next(request)

        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id is None:
            raw_key = _extract_api_key(request)
            if raw_key:
                tenant_id = await asyncio.to_thread(
                    _db_resolve_tenant_id, hash_api_key(raw_key)
                )
        if tenant_id is None:
            return await call_next(request)

        quota = await asyncio.to_thread(_db_quota_check, tenant_id)
        if quota is None:
            return await call_next(request)

        warn_headers = {}
        if quota["token_limit"]:
            remaining_tokens = quota["token_limit"] - quota["tokens_used"]
            warn_headers["X-RateLimit-Tokens-Remaining"] = str(max(remaining_tokens, 0))
            if remaining_tokens <= 0:
                QUOTA_DENIED_TOTAL.labels("token_limit").inc()
                return JSONResponse(
                    status_code=429,
                    headers=warn_headers,
                    content={"error": {"code": "quota_exceeded", "message": "Daily token budget exceeded"}},
                )

        if quota["spend_limit"]:
            remaining_spend = quota["spend_limit"] - quota["cost_used"]
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
