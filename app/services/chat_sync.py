from __future__ import annotations

import json
import time

from fastapi import Request

from app.db.repositories import RequestRepository, UsageRepository
from app.db.session import session_scope
from app.metrics import CACHE_HITS_TOTAL, CACHE_MISSES_TOTAL, FALLBACK_TOTAL
from app.provider import ProviderRequestError, ProviderResult
from app.runtime import AppRuntime
from app.schemas import ChatRequest, ChatResponse
from app.services.chat_shared import (
    CachedChatResult,
    ChatExecutionResult,
    ProviderExecution,
    ResolvedChatRequest,
    complete_request_record,
    cost_for_usage,
    resolve_chat_request,
    usage_from_provider_result,
)


async def load_cached_chat_result(
    runtime: AppRuntime,
    db,
    resolved: ResolvedChatRequest,
) -> tuple[str, CachedChatResult | None]:
    if runtime.redis_client is None or resolved.cache_lookup_key is None:
        return "bypass", None

    cached_raw = await runtime.redis_client.get(resolved.cache_lookup_key)
    if not cached_raw:
        CACHE_MISSES_TOTAL.labels(resolved.tenant.name, resolved.model_name).inc()
        return "miss", None

    CACHE_HITS_TOTAL.labels(resolved.tenant.name, resolved.model_name).inc()
    cached_entry = json.loads(cached_raw)
    usage = usage_from_provider_result(
        int(cached_entry.get("prompt_tokens") or 0),
        int(cached_entry.get("completion_tokens") or 0),
        int(cached_entry.get("total_tokens") or 0),
    )
    return (
        "hit",
        CachedChatResult(
            response=ChatResponse.model_validate(cached_entry["response"]),
            usage=usage,
            cost_usd=cost_for_usage(
                db,
                resolved.model_name,
                usage,
                cached_tokens=usage.total_tokens,
            ),
        ),
    )


async def store_cached_chat_result(
    runtime: AppRuntime,
    resolved: ResolvedChatRequest,
    result: ProviderExecution,
    *,
    cache_status: str,
) -> None:
    if runtime.redis_client is None or resolved.cache_lookup_key is None or cache_status != "miss":
        return

    await runtime.redis_client.set(
        resolved.cache_lookup_key,
        json.dumps(
            {
                "response": result.response.model_dump(),
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "total_tokens": result.usage.total_tokens,
                "cost_usd": result.cost_usd,
            },
            separators=(",", ":"),
        ),
        ex=runtime.settings.cache_ttl_seconds,
    )


async def execute_provider_request(
    runtime: AppRuntime,
    db,
    resolved: ResolvedChatRequest,
) -> ProviderExecution:
    provider_name = resolved.provider_name
    route_reason = resolved.route_reason
    try:
        provider_result: ProviderResult = await runtime.providers[resolved.provider_name].generate(
            resolved.routed_payload
        )
        runtime.health_tracker.record(resolved.provider_name, True)
    except ProviderRequestError:
        runtime.health_tracker.record(resolved.provider_name, False)
        fallback_provider_name = resolved.fallback_provider_name
        if fallback_provider_name is None:
            raise
        FALLBACK_TOTAL.labels("primary_error", resolved.provider_name, fallback_provider_name).inc()
        provider_name = fallback_provider_name
        route_reason = "primary_error"
        provider_result = await runtime.providers[fallback_provider_name].generate(resolved.routed_payload)
        runtime.health_tracker.record(fallback_provider_name, True)

    if resolved.route_reason == "primary_unhealthy" and resolved.fallback_provider_name:
        FALLBACK_TOTAL.labels(
            "primary_unhealthy",
            resolved.fallback_provider_name,
            resolved.provider_name,
        ).inc()

    usage = usage_from_provider_result(
        provider_result.prompt_tokens,
        provider_result.completion_tokens,
        provider_result.total_tokens,
    )
    return ProviderExecution(
        response=provider_result.response,
        usage=usage,
        cost_usd=cost_for_usage(db, resolved.model_name, usage),
        provider_name=provider_name,
        route_reason=route_reason,
    )


def build_chat_headers(
    *,
    resolved: ResolvedChatRequest,
    cache_status: str,
    provider_name: str,
    route_reason: str,
) -> dict[str, str]:
    return {
        "X-Model-Chosen": resolved.model_name,
        "X-Route-Reason": route_reason,
        "X-Provider": provider_name,
        "X-Cache": cache_status,
    }


async def execute_chat(runtime: AppRuntime, payload: ChatRequest, request: Request) -> ChatExecutionResult:
    with session_scope(runtime.session_factory) as db:
        requests = RequestRepository(db)
        usage_repo = UsageRepository(db)
        req_row = None
        started_at = time.perf_counter()
        try:
            resolved = resolve_chat_request(runtime, db, payload, request)
            cache_status, cached_result = await load_cached_chat_result(runtime, db, resolved)
            req_row = requests.create_in_progress(
                resolved.tenant.id,
                resolved.model_name,
                resolved.routed_payload.model_dump_json(),
            )

            if cached_result is not None:
                response = cached_result.response
                usage = cached_result.usage
                cost_value = cached_result.cost_usd
                provider_name = "cache"
                route_reason = "cache_hit"
            else:
                provider_result = await execute_provider_request(runtime, db, resolved)
                await store_cached_chat_result(runtime, resolved, provider_result, cache_status=cache_status)
                response = provider_result.response
                usage = provider_result.usage
                cost_value = provider_result.cost_usd
                provider_name = provider_result.provider_name
                route_reason = provider_result.route_reason

            complete_request_record(
                requests=requests,
                usage_repo=usage_repo,
                req_row=req_row,
                tenant=resolved.tenant,
                model_name=resolved.model_name,
                response=response,
                usage=usage,
                cost_value=cost_value,
                started_at=started_at,
            )
            return ChatExecutionResult(
                response=response,
                headers=build_chat_headers(
                    resolved=resolved,
                    cache_status=cache_status,
                    provider_name=provider_name,
                    route_reason=route_reason,
                ),
            )
        except Exception:
            if req_row is not None:
                requests.mark_status(req_row, "failed")
            raise
