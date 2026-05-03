from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from app.auth import candidate_api_key_hashes
from app.db.repositories import ApiKeyRepository, RequestRepository, TenantRepository
from app.db.session import session_scope
from app.errors import ConflictError, ForbiddenError, InvalidRequestError, NotFoundError
from app.runtime import AppRuntime
from app.schemas import (
    AdminStatusResponse,
    ApiKeyListResponse,
    BootstrapAdminResponse,
    CreateKeyRequest,
    CreateKeyResponse,
    CreateTenantKeyRequest,
    CreateTenantKeyResponse,
    CreateTenantRequest,
    CreateTenantResponse,
    DeleteResponse,
    LimitsRequest,
    LimitsResponse,
    ObservabilitySummaryResponse,
    PricingItem,
    PricingResponse,
    RevokeKeyByNameRequest,
    TenantInfo,
    TenantKeyInfo,
    TenantKeyListResponse,
    TenantListResponse,
    UsageSummaryResponse,
    VerifyKeyRequest,
    VerifyKeyResponse,
)
from app.services.admin import (
    admin_key_exists,
    assert_tenant_exists,
    bootstrap_admin_key,
    create_tenant_api_key,
    deactivate_key_by_id,
    get_admin_tenant_id,
    get_key_rows,
    get_pricing_rows,
    rotate_admin_key,
    upsert_pricing,
)
from app.services.admin import (
    admin_status as admin_status_value,
)
from app.services.observability import prom_query

router = APIRouter(prefix="/v1")


def _runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime


def _require_admin(request: Request) -> tuple[AppRuntime, UUID]:
    runtime = _runtime(request)
    admin_id = get_admin_tenant_id(runtime)
    tenant_id = getattr(request.state, "tenant_id", None)
    if admin_id is None or tenant_id != admin_id:
        raise ForbiddenError("Admin only")
    return runtime, admin_id


def _require_bootstrap_token(request: Request) -> AppRuntime:
    runtime = _runtime(request)
    bootstrap_token = request.headers.get("X-Bootstrap-Token", "")
    if bootstrap_token != runtime.settings.bootstrap_admin_token:
        raise ForbiddenError("Invalid bootstrap token")
    return runtime


def _normalize_tier(value: str | None) -> str:
    return value.strip() if value and value.strip() else "free"


@router.post("/admin/keys", response_model=CreateKeyResponse)
async def create_key(payload: CreateKeyRequest, request: Request):
    runtime, _ = _require_admin(request)
    requested_name = payload.name or payload.tenant
    if not requested_name:
        raise InvalidRequestError("Name is required")
    raw_key = create_tenant_api_key(runtime, requested_name, requested_name)
    return CreateKeyResponse(tenant=requested_name, api_key=raw_key)


@router.get("/admin/status", response_model=AdminStatusResponse)
async def admin_status(request: Request):
    return AdminStatusResponse(admin_initialized=admin_status_value(_runtime(request)))


@router.post("/admin/bootstrap", response_model=BootstrapAdminResponse)
async def bootstrap_admin(request: Request):
    runtime = _require_bootstrap_token(request)
    if admin_key_exists(runtime):
        raise ForbiddenError("Admin already initialized")
    return BootstrapAdminResponse(api_key=bootstrap_admin_key(runtime))


@router.get("/admin/keys", response_model=ApiKeyListResponse)
async def list_keys(request: Request):
    runtime, _ = _require_admin(request)
    rows = get_key_rows(runtime)
    keys = [
        {
            "id": str(key.id),
            "name": key.name,
            "tenant": tenant.name,
            "active": bool(key.active),
            "created_at": key.created_at.isoformat(),
        }
        for key, tenant in rows
    ]
    return ApiKeyListResponse(keys=keys)


@router.delete("/admin/keys/{key_id}", response_model=DeleteResponse)
async def delete_key(key_id: str, request: Request):
    runtime, _ = _require_admin(request)
    result = deactivate_key_by_id(runtime, key_id)
    if result == "invalid":
        raise InvalidRequestError("Invalid key id")
    if result == "missing":
        raise NotFoundError("Key not found")
    return DeleteResponse(status="ok")


@router.get("/admin/tenants", response_model=TenantListResponse)
async def list_tenants(request: Request):
    runtime, _ = _require_admin(request)
    with session_scope(runtime.session_factory) as db:
        rows = TenantRepository(db).list_all()
        tenants = [
            TenantInfo(
                tenant=row.name,
                tier=row.tier,
                created_at=row.created_at.isoformat() if row.created_at else None,
                token_limit_per_day=row.token_limit_per_day,
                spend_limit_per_day_usd=row.spend_limit_per_day_usd,
            )
            for row in rows
        ]
        return TenantListResponse(tenants=tenants)


@router.post("/admin/tenants", response_model=CreateTenantResponse)
async def create_tenant(payload: CreateTenantRequest, request: Request):
    runtime, _ = _require_admin(request)
    with session_scope(runtime.session_factory) as db:
        tenants = TenantRepository(db)
        existing = tenants.get_by_name(payload.tenant)
        if existing is not None:
            raise ConflictError("Tenant already exists")
        tier = _normalize_tier(payload.tier)
        tenants.create(payload.tenant, tier=tier)
        return CreateTenantResponse(tenant=payload.tenant, tier=tier)


@router.get("/admin/tenants/{tenant_name}/keys", response_model=TenantKeyListResponse)
async def list_tenant_keys(tenant_name: str, request: Request):
    runtime, _ = _require_admin(request)
    with session_scope(runtime.session_factory) as db:
        tenant = TenantRepository(db).get_by_name(tenant_name)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        keys = [
            TenantKeyInfo(
                name=key.name,
                active=bool(key.active),
                created_at=key.created_at.isoformat() if key.created_at else None,
                key_last6=key.key_hash[-6:] if key.key_hash else None,
            )
            for key in tenant.api_keys
        ]
        return TenantKeyListResponse(keys=keys)


@router.post("/admin/tenants/{tenant_name}/keys", response_model=CreateTenantKeyResponse)
async def create_tenant_key(tenant_name: str, payload: CreateTenantKeyRequest, request: Request):
    runtime, _ = _require_admin(request)
    assert_tenant_exists(runtime, tenant_name)
    raw_key = create_tenant_api_key(runtime, tenant_name, payload.name)
    return CreateTenantKeyResponse(tenant=tenant_name, name=payload.name, api_key=raw_key)


@router.post("/admin/keys/verify", response_model=VerifyKeyResponse)
async def verify_key(payload: VerifyKeyRequest, request: Request):
    runtime, _ = _require_admin(request)
    key_hashes = candidate_api_key_hashes(payload.api_key, runtime.settings.api_key_pepper)
    with session_scope(runtime.session_factory) as db:
        return VerifyKeyResponse(
            matches=ApiKeyRepository(db).matches_any_hash(payload.tenant, payload.name, key_hashes)
        )


@router.post("/admin/tenants/{tenant_name}/keys/revoke", response_model=DeleteResponse)
async def revoke_tenant_key(tenant_name: str, payload: RevokeKeyByNameRequest, request: Request):
    runtime, _ = _require_admin(request)
    with session_scope(runtime.session_factory) as db:
        row = ApiKeyRepository(db).deactivate_active_by_tenant_and_name(tenant_name, payload.name)
        if row is None:
            raise NotFoundError("Active key not found")
        return DeleteResponse(status="ok")


@router.post("/admin/rotate", response_model=BootstrapAdminResponse)
async def rotate_admin(request: Request):
    runtime, _ = _require_admin(request)
    if not runtime.settings.allow_admin_reset:
        raise ForbiddenError("Admin reset disabled")
    return BootstrapAdminResponse(api_key=rotate_admin_key(runtime))


@router.post("/admin/limits", response_model=LimitsResponse)
async def set_limits(payload: LimitsRequest, request: Request):
    runtime, _ = _require_admin(request)
    with session_scope(runtime.session_factory) as db:
        tenants = TenantRepository(db)
        tenant = tenants.get_by_name(payload.tenant)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        tenant = tenants.update_limits(
            tenant,
            token_limit_per_day=payload.token_limit_per_day,
            spend_limit_per_day_usd=payload.spend_limit_per_day_usd,
        )
        return LimitsResponse(
            tenant=payload.tenant,
            token_limit_per_day=tenant.token_limit_per_day,
            spend_limit_per_day_usd=tenant.spend_limit_per_day_usd,
        )


@router.post("/admin/health/reset", response_model=DeleteResponse)
async def reset_health(request: Request):
    runtime, _ = _require_admin(request)
    runtime.health_tracker.reset()
    return DeleteResponse(status="ok")


@router.get("/admin/usage/{tenant_name}", response_model=UsageSummaryResponse)
async def usage_summary(tenant_name: str, request: Request):
    runtime, _ = _require_admin(request)
    with session_scope(runtime.session_factory) as db:
        tenants = TenantRepository(db)
        tenant = tenants.get_by_name(tenant_name)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        requests, tokens, cost = RequestRepository(db).get_request_counts(tenant.id)
        return UsageSummaryResponse(tenant=tenant_name, requests=requests, tokens=tokens, cost_usd=cost)


@router.get("/observability/summary", response_model=ObservabilitySummaryResponse)
async def observability_summary(request: Request):
    runtime = _runtime(request)
    request_rate = await prom_query(runtime, 'sum(rate(http_requests_total[5m]))')
    error_rate = await prom_query(runtime, 'sum(rate(http_requests_total{status_code=~"4..|5.."}[5m]))')
    total_rate = await prom_query(runtime, 'sum(rate(http_requests_total[5m]))')
    error_ratio = (error_rate / total_rate) if total_rate > 0 else 0.0
    p95_latency = await prom_query(
        runtime,
        "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))",
    )
    cache_hits = await prom_query(runtime, 'sum(rate(cache_hits_total[5m]))')
    cache_misses = await prom_query(runtime, 'sum(rate(cache_misses_total[5m]))')
    rate_limited = await prom_query(runtime, 'sum(rate(rate_limited_total[5m]))')
    tokens_total = await prom_query(runtime, 'sum(tokens_total)')
    cost_total = await prom_query(runtime, 'sum(cost_total)')
    cache_total = cache_hits + cache_misses
    cache_hit_rate = (cache_hits / cache_total) if cache_total > 0 else 0.0
    return ObservabilitySummaryResponse(
        request_rate_per_s=request_rate,
        error_rate=error_ratio,
        p95_latency_ms=p95_latency * 1000,
        cache_hit_rate=cache_hit_rate,
        rate_limited_per_s=rate_limited,
        tokens_total=tokens_total,
        cost_total=cost_total,
        scope="global",
        tenant=None,
    )


@router.get("/admin/pricing", response_model=PricingResponse)
async def get_pricing(request: Request):
    runtime, _ = _require_admin(request)
    rows = get_pricing_rows(runtime)
    items = [
        PricingItem(
            model=row.model,
            input_per_1k=float(row.input_per_1k),
            output_per_1k=float(row.output_per_1k),
            cached_per_1k=float(row.cached_per_1k),
        )
        for row in rows
    ]
    return PricingResponse(items=items)


@router.put("/admin/pricing", response_model=PricingResponse)
async def set_pricing(payload: PricingResponse, request: Request):
    runtime, _ = _require_admin(request)
    upsert_pricing(runtime, payload.items)
    return payload
