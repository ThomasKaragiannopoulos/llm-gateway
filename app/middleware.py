from __future__ import annotations

import json
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from app.auth import candidate_api_key_hashes
from app.db.repositories import ApiKeyRepository, TenantRepository, UsageRepository
from app.db.session import session_scope
from app.metrics import QUOTA_DENIED_TOTAL, RATE_LIMITED_TOTAL, REQUEST_LATENCY, REQUESTS_TOTAL
from app.runtime import AppRuntime

PUBLIC_PATHS = {
    "/health",
    "/ready",
    "/metrics",
    "/health/ollama",
    "/health/grafana",
    "/health/prometheus",
    "/v1/admin/status",
    "/v1/admin/bootstrap",
}


def _json_error(status_code: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={"error": {"code": code, "message": message}},
    )


def _is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS


def _skip_policy_enforcement(request: Request) -> bool:
    return request.method == "OPTIONS" or _is_public_path(request.url.path) or request.url.path.startswith("/v1/admin")


def create_api_key_auth_middleware(runtime: AppRuntime):
    async def api_key_auth(request: Request, call_next):
        if request.method == "OPTIONS" or _is_public_path(request.url.path):
            return await call_next(request)

        raw_key = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            raw_key = auth_header.split(" ", 1)[1].strip()
        if not raw_key:
            raw_key = request.headers.get("X-API-Key")
        if not raw_key:
            return _json_error(401, "unauthorized", "Missing API key")

        key_hashes = candidate_api_key_hashes(raw_key, runtime.settings.api_key_pepper)
        with session_scope(runtime.session_factory) as db:
            api_key = ApiKeyRepository(db).get_active_by_hashes(key_hashes)
        if api_key is None:
            return _json_error(401, "unauthorized", "Invalid API key")

        request.state.tenant_id = api_key.tenant_id
        return await call_next(request)

    return api_key_auth


def create_rate_limit_middleware(runtime: AppRuntime):
    async def rate_limit_requests(request: Request, call_next):
        if _skip_policy_enforcement(request):
            return await call_next(request)

        if runtime.redis_client is None:
            return _json_error(503, "rate_limit_unavailable", "Redis unavailable")

        tenant_id = getattr(request.state, "tenant_id", "unknown")
        minute_bucket = int(time.time() // 60)
        key = f"rl:req:{tenant_id}:{minute_bucket}"

        count = await runtime.redis_client.incr(key)
        if count == 1:
            await runtime.redis_client.expire(key, 60)
        if count > runtime.settings.requests_per_minute:
            retry_after = 60 - int(time.time() % 60)
            RATE_LIMITED_TOTAL.labels("requests_per_minute").inc()
            return _json_error(
                429,
                "rate_limited",
                "Request limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        token_estimate = 2
        token_key = f"rl:tokens:{tenant_id}:{minute_bucket}"
        token_count = await runtime.redis_client.incrby(token_key, token_estimate)
        if token_count == token_estimate:
            await runtime.redis_client.expire(token_key, 60)
        if token_count > runtime.settings.tokens_per_minute:
            retry_after = 60 - int(time.time() % 60)
            RATE_LIMITED_TOTAL.labels("tokens_per_minute").inc()
            return _json_error(
                429,
                "rate_limited",
                "Token limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)

    return rate_limit_requests


def create_quota_middleware(runtime: AppRuntime):
    async def quota_limits(request: Request, call_next):
        if _skip_policy_enforcement(request):
            return await call_next(request)

        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id is None:
            return await call_next(request)

        with session_scope(runtime.session_factory) as db:
            tenant = TenantRepository(db).get_by_id(tenant_id)
            if tenant is None:
                return await call_next(request)
            if tenant.token_limit_per_day is None and tenant.spend_limit_per_day_usd is None:
                return await call_next(request)

            tokens_used, cost_used = UsageRepository(db).daily_totals(tenant.id)
            warn_headers = {}
            if tenant.token_limit_per_day:
                remaining_tokens = tenant.token_limit_per_day - tokens_used
                warn_headers["X-RateLimit-Tokens-Remaining"] = str(max(remaining_tokens, 0))
                if remaining_tokens <= 0:
                    QUOTA_DENIED_TOTAL.labels("token_limit").inc()
                    return _json_error(429, "quota_exceeded", "Daily token budget exceeded", headers=warn_headers)
            if tenant.spend_limit_per_day_usd:
                remaining_spend = tenant.spend_limit_per_day_usd - cost_used
                warn_headers["X-RateLimit-Spend-Remaining"] = f"{max(remaining_spend, 0):.6f}"
                if remaining_spend <= 0:
                    QUOTA_DENIED_TOTAL.labels("spend_limit").inc()
                    return _json_error(429, "quota_exceeded", "Daily spend budget exceeded", headers=warn_headers)

            response = await call_next(request)
            for key, value in warn_headers.items():
                response.headers[key] = value
            return response

    return quota_limits


def create_logging_middleware(runtime: AppRuntime):
    async def log_requests(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        idempotency_key = request.headers.get("Idempotency-Key")
        start = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
        finally:
            elapsed_seconds = time.perf_counter() - start
            payload = {
                "message": "request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": getattr(response, "status_code", None),
                "duration_ms": round(elapsed_seconds * 1000, 2),
                "idempotency_key": idempotency_key,
                "tenant_id": str(getattr(request.state, "tenant_id", "")) or None,
            }
            runtime.logger.info(json.dumps(payload, separators=(",", ":")))

        if response is None:
            return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Unhandled error"}})

        response.headers["X-Request-Id"] = request_id
        if idempotency_key:
            response.headers["Idempotency-Key"] = idempotency_key

        status_code = str(getattr(response, "status_code", 500))
        REQUESTS_TOTAL.labels(request.method, request.url.path, status_code).inc()
        REQUEST_LATENCY.labels(request.method, request.url.path).observe(elapsed_seconds)
        return response

    return log_requests
