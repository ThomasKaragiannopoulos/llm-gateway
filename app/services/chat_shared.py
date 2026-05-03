from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from app.db.models import Request as RequestRow
from app.db.models import Tenant
from app.db.repositories import (
    PricingRepository,
    RequestRepository,
    TenantRepository,
    UsageRepository,
)
from app.metrics import (
    COST_TOTAL,
    TENANT_COST_TOTAL,
    TENANT_REQUESTS_TOTAL,
    TENANT_TOKENS_TOTAL,
    TOKENS_TOTAL,
)
from app.pricing import cost_usd, merge_pricing
from app.runtime import AppRuntime
from app.schemas import ChatRequest, ChatResponse
from app.services.providers import (
    cache_key,
    cacheable_request,
    estimate_tokens,
    resolve_model_name,
    resolve_route,
)


@dataclass(frozen=True)
class ChatExecutionResult:
    response: ChatResponse
    headers: dict[str, str]


@dataclass(frozen=True)
class UsageSnapshot:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class ResolvedChatRequest:
    tenant: Tenant
    model_name: str
    routed_payload: ChatRequest
    provider_name: str
    route_reason: str
    fallback_provider_name: str | None
    cache_lookup_key: str | None


@dataclass(frozen=True)
class CachedChatResult:
    response: ChatResponse
    usage: UsageSnapshot
    cost_usd: float


@dataclass(frozen=True)
class ProviderExecution:
    response: ChatResponse
    usage: UsageSnapshot
    cost_usd: float
    provider_name: str
    route_reason: str


@dataclass
class StreamingSessionState:
    response_id: str
    created: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    used_provider: str | None = None
    completed: bool = False
    canceled: bool = False
    failed: bool = False
    done_sent: bool = False
    content_parts: list[str] = field(default_factory=list)

    def usage_snapshot(self) -> UsageSnapshot:
        return UsageSnapshot(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
        )


def pricing_map(db) -> dict[str, dict[str, float]]:
    return merge_pricing([{"model": model, **values} for model, values in PricingRepository(db).get_map().items()])


def cost_for_usage(db, model_name: str, usage: UsageSnapshot, *, cached_tokens: int = 0) -> float:
    return cost_usd(
        model_name,
        usage.prompt_tokens,
        usage.completion_tokens,
        cached_tokens,
        pricing_map=pricing_map(db),
    )


def resolve_tenant(db, request: Request) -> Tenant:
    tenants = TenantRepository(db)
    tenant_id = getattr(request.state, "tenant_id", None)
    tenant = tenants.get_by_id(tenant_id) if tenant_id is not None else None
    return tenant or tenants.ensure_default()


def resolve_chat_request(
    runtime: AppRuntime,
    db,
    payload: ChatRequest,
    request: Request,
    *,
    stream: bool = False,
) -> ResolvedChatRequest:
    tenant = resolve_tenant(db, request)
    decision = resolve_route(runtime, tenant.tier, payload.model)
    model_name = resolve_model_name(runtime, decision.provider, decision.model)
    routed_payload = payload.model_copy(update={"model": model_name, "stream": stream})
    lookup_key = None
    if runtime.redis_client is not None and cacheable_request(routed_payload):
        lookup_key = cache_key(runtime, str(tenant.id), routed_payload)
    return ResolvedChatRequest(
        tenant=tenant,
        model_name=model_name,
        routed_payload=routed_payload,
        provider_name=decision.provider,
        route_reason=decision.reason,
        fallback_provider_name=decision.fallback_provider,
        cache_lookup_key=lookup_key,
    )


def usage_from_provider_result(prompt_tokens: int, completion_tokens: int, total_tokens: int) -> UsageSnapshot:
    return UsageSnapshot(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def estimate_stream_usage(routed_payload: ChatRequest, content: str, usage: UsageSnapshot) -> UsageSnapshot:
    total_tokens = usage.prompt_tokens + usage.completion_tokens
    if total_tokens == 0:
        total_tokens = estimate_tokens(routed_payload.messages, content)
        return UsageSnapshot(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=total_tokens,
            total_tokens=total_tokens,
        )
    return usage


def build_completion_event(
    *,
    response_id: str,
    model_name: str,
    created: int,
    usage: UsageSnapshot,
    provider_name: str | None,
) -> dict[str, Any]:
    return {
        "id": response_id,
        "model": model_name,
        "created": created,
        "content": "",
        "done": True,
        "usage": {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
        "provider": provider_name,
    }


def record_metrics(tenant: Tenant, model_name: str, total_tokens: int, cost_value: float) -> None:
    TOKENS_TOTAL.labels(model_name).inc(total_tokens or 0)
    COST_TOTAL.labels(model_name).inc(cost_value or 0.0)
    TENANT_REQUESTS_TOTAL.labels(tenant.name, tenant.tier).inc()
    TENANT_TOKENS_TOTAL.labels(tenant.name, tenant.tier).inc(total_tokens or 0)
    TENANT_COST_TOTAL.labels(tenant.name, tenant.tier).inc(cost_value or 0.0)


def complete_request_record(
    *,
    requests: RequestRepository,
    usage_repo: UsageRepository,
    req_row: RequestRow,
    tenant: Tenant,
    model_name: str,
    response: ChatResponse,
    usage: UsageSnapshot,
    cost_value: float,
    started_at: float,
) -> None:
    requests.mark_completed(
        req_row,
        response.model_dump_json(),
        int((time.perf_counter() - started_at) * 1000),
        usage.prompt_tokens,
        usage.completion_tokens,
        usage.total_tokens,
        cost_value,
    )
    usage_repo.add(tenant.id, req_row.id, model_name, usage.total_tokens, cost_value)
    record_metrics(tenant, model_name, req_row.total_tokens or 0, req_row.cost_usd or 0.0)
