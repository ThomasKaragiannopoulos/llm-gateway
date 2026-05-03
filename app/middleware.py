from __future__ import annotations

import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from app.metrics import REQUEST_LATENCY, REQUESTS_TOTAL
from app.runtime import AppRuntime
from app.services.contracts import RawRequestContext, RequestContext
from app.services.observability import log_event
from app.services.policy import (
    authenticate_request,
    enforce_rate_limits_async,
    evaluate_quota,
    is_public_path,
    skip_policy_enforcement,
)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or request.headers.get("X-Request-Id") or str(uuid.uuid4())


def _raw_context(request: Request) -> RawRequestContext:
    return RawRequestContext(
        method=request.method,
        path=request.url.path,
        request_id=_request_id(request),
        headers=dict(request.headers),
        idempotency_key=request.headers.get("Idempotency-Key"),
    )


def _request_context(request: Request) -> RequestContext:
    return RequestContext(
        method=request.method,
        path=request.url.path,
        request_id=_request_id(request),
        tenant_id=getattr(request.state, "tenant_id", None),
        idempotency_key=request.headers.get("Idempotency-Key"),
    )


def _json_error(status_code: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={"error": {"code": code, "message": message}},
    )


def create_api_key_auth_middleware(runtime: AppRuntime):
    async def api_key_auth(request: Request, call_next):
        if request.method == "OPTIONS" or is_public_path(request.url.path):
            return await call_next(request)
        try:
            auth_context = authenticate_request(runtime, _raw_context(request))
        except Exception as exc:
            if hasattr(exc, "status_code") and hasattr(exc, "code") and hasattr(exc, "message"):
                return _json_error(exc.status_code, exc.code, exc.message, headers=getattr(exc, "headers", None))
            raise

        request.state.tenant_id = auth_context.tenant_id
        request.state.api_key_id = auth_context.api_key_id
        return await call_next(request)

    return api_key_auth


def create_rate_limit_middleware(runtime: AppRuntime):
    async def rate_limit_requests(request: Request, call_next):
        if skip_policy_enforcement(request.method, request.url.path):
            return await call_next(request)
        try:
            await enforce_rate_limits_async(runtime, _request_context(request))
        except Exception as exc:
            if hasattr(exc, "status_code") and hasattr(exc, "code") and hasattr(exc, "message"):
                return _json_error(exc.status_code, exc.code, exc.message, headers=getattr(exc, "headers", None))
            raise
        return await call_next(request)

    return rate_limit_requests


def create_quota_middleware(runtime: AppRuntime):
    async def quota_limits(request: Request, call_next):
        if skip_policy_enforcement(request.method, request.url.path):
            return await call_next(request)
        try:
            quota_headers = evaluate_quota(runtime, _request_context(request))
        except Exception as exc:
            if hasattr(exc, "status_code") and hasattr(exc, "code") and hasattr(exc, "message"):
                return _json_error(exc.status_code, exc.code, exc.message, headers=getattr(exc, "headers", None))
            raise

        response = await call_next(request)
        for key, value in quota_headers.values.items():
            response.headers[key] = value
        return response

    return quota_limits


def create_logging_middleware(runtime: AppRuntime):
    async def log_requests(request: Request, call_next):
        request_id = _request_id(request)
        request.state.request_id = request_id
        idempotency_key = request.headers.get("Idempotency-Key")
        start = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
        finally:
            elapsed_seconds = time.perf_counter() - start
            log_event(
                runtime,
                "request",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=getattr(response, "status_code", None),
                duration_ms=round(elapsed_seconds * 1000, 2),
                idempotency_key=idempotency_key,
                tenant_id=str(getattr(request.state, "tenant_id", "")) or None,
            )

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
