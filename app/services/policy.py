from __future__ import annotations

import time
from dataclasses import dataclass

from redis.exceptions import RedisError

from app.auth import candidate_api_key_hashes
from app.db.repositories import ApiKeyRepository, TenantRepository, UsageRepository
from app.db.session import session_scope
from app.errors import DependencyUnavailableError, UnauthorizedError
from app.metrics import QUOTA_DENIED_TOTAL, RATE_LIMITED_TOTAL
from app.runtime import AppRuntime
from app.services.contracts import AuthenticatedContext, RawRequestContext
from app.services.observability import log_policy_event

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


@dataclass(frozen=True)
class QuotaHeaders:
    values: dict[str, str]


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS


def skip_policy_enforcement(method: str, path: str) -> bool:
    return method == "OPTIONS" or is_public_path(path) or path.startswith("/v1/admin")


def extract_api_key(headers: dict[str, str] | RawRequestContext) -> str | None:
    values = headers.headers if isinstance(headers, RawRequestContext) else headers
    auth_header = values.get("Authorization") or values.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            return token
    api_key = values.get("X-API-Key") or values.get("x-api-key")
    return api_key.strip() if api_key else None


def authenticate_request(runtime: AppRuntime, context: RawRequestContext) -> AuthenticatedContext:
    raw_key = extract_api_key(context)
    if not raw_key:
        log_policy_event(runtime, "auth_denied", context, reason="missing_api_key")
        raise UnauthorizedError("Missing API key")

    key_hashes = candidate_api_key_hashes(raw_key, runtime.settings.api_key_pepper)
    with session_scope(runtime.session_factory) as db:
        api_key = ApiKeyRepository(db).authenticate_hashes(key_hashes)
    if api_key is None:
        log_policy_event(runtime, "auth_denied", context, reason="invalid_api_key")
        raise UnauthorizedError("Invalid API key")

    log_policy_event(runtime, "auth_granted", context, tenant_id=str(api_key.tenant_id), api_key_id=str(api_key.id))
    return AuthenticatedContext(tenant_id=api_key.tenant_id, api_key_id=api_key.id)


async def enforce_rate_limits_async(runtime: AppRuntime, context, *, token_estimate: int = 2) -> None:
    tenant_id = context.tenant_id
    if tenant_id is None:
        return
    if runtime.redis_client is None:
        log_policy_event(runtime, "rate_limit_dependency_down", context, reason="redis_unavailable")
        raise DependencyUnavailableError("rate_limit_unavailable", "Redis unavailable")

    minute_bucket = int(time.time() // 60)
    request_key = f"rl:req:{tenant_id}:{minute_bucket}"
    token_key = f"rl:tokens:{tenant_id}:{minute_bucket}"

    try:
        request_count = await runtime.redis_client.incr(request_key)
        if request_count == 1:
            await runtime.redis_client.expire(request_key, 60)
        if request_count > runtime.settings.requests_per_minute:
            retry_after = 60 - int(time.time() % 60)
            RATE_LIMITED_TOTAL.labels("requests_per_minute").inc()
            log_policy_event(runtime, "rate_limit_denied", context, reason="requests_per_minute", retry_after=retry_after)
            raise DependencyUnavailableError(
                "rate_limited",
                "Request limit exceeded",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        token_count = await runtime.redis_client.incrby(token_key, token_estimate)
        if token_count == token_estimate:
            await runtime.redis_client.expire(token_key, 60)
        if token_count > runtime.settings.tokens_per_minute:
            retry_after = 60 - int(time.time() % 60)
            RATE_LIMITED_TOTAL.labels("tokens_per_minute").inc()
            log_policy_event(runtime, "rate_limit_denied", context, reason="tokens_per_minute", retry_after=retry_after)
            raise DependencyUnavailableError(
                "rate_limited",
                "Token limit exceeded",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
    except RedisError as err:
        log_policy_event(runtime, "rate_limit_dependency_down", context, reason="redis_unavailable")
        raise DependencyUnavailableError("rate_limit_unavailable", "Redis unavailable") from err


def evaluate_quota(runtime: AppRuntime, context) -> QuotaHeaders:
    tenant_id = context.tenant_id
    if tenant_id is None:
        return QuotaHeaders(values={})

    with session_scope(runtime.session_factory) as db:
        tenant = TenantRepository(db).get_by_id(tenant_id)
        if tenant is None:
            return QuotaHeaders(values={})
        if tenant.token_limit_per_day is None and tenant.spend_limit_per_day_usd is None:
            return QuotaHeaders(values={})

        tokens_used, cost_used = UsageRepository(db).daily_totals(tenant.id)
        headers: dict[str, str] = {}
        if tenant.token_limit_per_day:
            remaining_tokens = tenant.token_limit_per_day - tokens_used
            headers["X-RateLimit-Tokens-Remaining"] = str(max(remaining_tokens, 0))
            if remaining_tokens <= 0:
                QUOTA_DENIED_TOTAL.labels("token_limit").inc()
                log_policy_event(runtime, "quota_denied", context, reason="token_limit", tenant_id=str(tenant.id))
                raise DependencyUnavailableError(
                    "quota_exceeded",
                    "Daily token budget exceeded",
                    status_code=429,
                    headers=headers,
                )
        if tenant.spend_limit_per_day_usd:
            remaining_spend = tenant.spend_limit_per_day_usd - cost_used
            headers["X-RateLimit-Spend-Remaining"] = f"{max(remaining_spend, 0):.6f}"
            if remaining_spend <= 0:
                QUOTA_DENIED_TOTAL.labels("spend_limit").inc()
                log_policy_event(runtime, "quota_denied", context, reason="spend_limit", tenant_id=str(tenant.id))
                raise DependencyUnavailableError(
                    "quota_exceeded",
                    "Daily spend budget exceeded",
                    status_code=429,
                    headers=headers,
                )
        return QuotaHeaders(values=headers)
