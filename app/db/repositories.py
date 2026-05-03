from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import ApiKey, Pricing, Request, Tenant, UsageEvent

ApiKeyWithTenant = tuple[ApiKey, Tenant]
RequestStatus = Literal["in_progress", "completed", "failed", "canceled"]


def get_tenant_by_id(db: Session, tenant_id: uuid.UUID | None) -> Tenant | None:
    return db.query(Tenant).filter(Tenant.id == tenant_id).one_or_none()


def get_tenant_by_name(db: Session, tenant_name: str) -> Tenant | None:
    return db.query(Tenant).filter(Tenant.name == tenant_name).one_or_none()


def ensure_tenant(db: Session, tenant_name: str, tier: str = "free") -> Tenant:
    tenant = get_tenant_by_name(db, tenant_name)
    if tenant is None:
        tenant = Tenant(name=tenant_name, tier=tier)
        db.add(tenant)
        db.flush()
        db.refresh(tenant)
    return tenant


def ensure_default_tenant(db: Session) -> Tenant:
    return ensure_tenant(db, "default")


def ensure_admin_tenant(db: Session) -> Tenant:
    return ensure_tenant(db, "admin")


def get_active_api_key_by_hash(db: Session, key_hash: str) -> ApiKey | None:
    return db.query(ApiKey).filter(ApiKey.key_hash == key_hash, ApiKey.active.is_(True)).one_or_none()


def count_api_keys(db: Session) -> tuple[int, int]:
    total_keys = db.query(ApiKey).count()
    active_keys = db.query(ApiKey).filter(ApiKey.active.is_(True)).count()
    return int(total_keys), int(active_keys)


def get_pricing_map(db: Session) -> dict[str, dict[str, float]]:
    rows = db.query(Pricing).all()
    return {
        row.model: {
            "input_per_1k": row.input_per_1k,
            "output_per_1k": row.output_per_1k,
            "cached_per_1k": row.cached_per_1k,
        }
        for row in rows
    }


def list_api_keys(db: Session) -> Sequence[ApiKeyWithTenant]:
    return (
        db.query(ApiKey, Tenant)
        .join(Tenant, Tenant.id == ApiKey.tenant_id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )


def parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def get_request_counts(db: Session, tenant_id: uuid.UUID) -> tuple[int, int, float]:
    request_count = db.query(func.count(Request.id)).filter(Request.tenant_id == tenant_id).scalar()
    totals = (
        db.query(
            func.coalesce(func.sum(Request.total_tokens), 0),
            func.coalesce(func.sum(Request.cost_usd), 0.0),
        )
        .filter(Request.tenant_id == tenant_id)
        .filter(Request.status == "completed")
        .one()
    )
    return int(request_count or 0), int(totals[0] or 0), float(totals[1] or 0.0)


def get_daily_usage_totals(db: Session, tenant_id: uuid.UUID) -> tuple[int, float]:
    today = func.date(func.now())
    totals = (
        db.query(
            func.coalesce(func.sum(UsageEvent.tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0.0),
        )
        .filter(UsageEvent.tenant_id == tenant_id)
        .filter(func.date(UsageEvent.created_at) == today)
        .one()
    )
    return int(totals[0] or 0), float(totals[1] or 0.0)


class TenantRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, tenant_id: uuid.UUID | None) -> Tenant | None:
        return get_tenant_by_id(self.db, tenant_id)

    def get_by_name(self, tenant_name: str) -> Tenant | None:
        return get_tenant_by_name(self.db, tenant_name)

    def ensure(self, tenant_name: str, tier: str = "free") -> Tenant:
        return ensure_tenant(self.db, tenant_name, tier)

    def ensure_default(self) -> Tenant:
        return ensure_default_tenant(self.db)

    def ensure_admin(self) -> Tenant:
        return ensure_admin_tenant(self.db)

    def list_all(self) -> list[Tenant]:
        return self.db.query(Tenant).order_by(Tenant.created_at.desc()).all()

    def create(self, tenant_name: str, tier: str = "free") -> Tenant:
        tenant = Tenant(name=tenant_name, tier=tier)
        self.db.add(tenant)
        self.db.flush()
        self.db.refresh(tenant)
        return tenant

    def update_limits(
        self,
        tenant: Tenant,
        *,
        token_limit_per_day: int | None,
        spend_limit_per_day_usd: float | None,
    ) -> Tenant:
        tenant.token_limit_per_day = token_limit_per_day
        tenant.spend_limit_per_day_usd = spend_limit_per_day_usd
        self.db.add(tenant)
        self.db.flush()
        self.db.refresh(tenant)
        return tenant


class ApiKeyRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active_by_hash(self, key_hash: str) -> ApiKey | None:
        return get_active_api_key_by_hash(self.db, key_hash)

    def get_active_by_hashes(self, key_hashes: Sequence[str]) -> ApiKey | None:
        return (
            self.db.query(ApiKey)
            .filter(ApiKey.key_hash.in_(tuple(key_hashes)), ApiKey.active.is_(True))
            .one_or_none()
        )

    def authenticate_hashes(self, key_hashes: Sequence[str]) -> ApiKey | None:
        row = self.get_active_by_hashes(key_hashes)
        if row is None:
            return None
        row.last_used_at = func.now()
        self.db.add(row)
        self.db.flush()
        return row

    def count(self) -> tuple[int, int]:
        return count_api_keys(self.db)

    def list_with_tenants(self) -> Sequence[ApiKeyWithTenant]:
        return list_api_keys(self.db)

    def add(self, tenant_id: uuid.UUID, key_hash: str, name: str | None = None, active: bool = True) -> ApiKey:
        row = ApiKey(tenant_id=tenant_id, name=name, key_hash=key_hash, active=active)
        self.db.add(row)
        self.db.flush()
        self.db.refresh(row)
        return row

    def deactivate_by_id(self, key_id: uuid.UUID) -> ApiKey | None:
        key = self.db.query(ApiKey).filter(ApiKey.id == key_id).one_or_none()
        if key is None:
            return None
        key.active = False
        self.db.add(key)
        return key

    def get_active_by_tenant_and_name(self, tenant_name: str, key_name: str) -> ApiKey | None:
        return (
            self.db.query(ApiKey)
            .join(Tenant, Tenant.id == ApiKey.tenant_id)
            .filter(Tenant.name == tenant_name, ApiKey.name == key_name, ApiKey.active.is_(True))
            .one_or_none()
        )

    def deactivate_active_by_tenant_and_name(self, tenant_name: str, key_name: str) -> ApiKey | None:
        key = self.get_active_by_tenant_and_name(tenant_name, key_name)
        if key is None:
            return None
        key.active = False
        self.db.add(key)
        return key

    def matches_any_hash(self, tenant_name: str, key_name: str, key_hashes: Sequence[str]) -> bool:
        row = (
            self.db.query(ApiKey)
            .join(Tenant, Tenant.id == ApiKey.tenant_id)
            .filter(
                Tenant.name == tenant_name,
                ApiKey.name == key_name,
                ApiKey.key_hash.in_(tuple(key_hashes)),
                ApiKey.active.is_(True),
            )
            .one_or_none()
        )
        return row is not None

    def deactivate_for_tenant(self, tenant_id: uuid.UUID) -> None:
        self.db.query(ApiKey).filter(ApiKey.tenant_id == tenant_id).update({ApiKey.active: False})

    def get_active_for_tenant(self, tenant_id: uuid.UUID) -> ApiKey | None:
        return self.db.query(ApiKey).filter(ApiKey.tenant_id == tenant_id, ApiKey.active.is_(True)).first()


class PricingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_map(self) -> dict[str, dict[str, float]]:
        return get_pricing_map(self.db)

    def list_all(self) -> list[Pricing]:
        return self.db.query(Pricing).order_by(Pricing.model.asc()).all()

    def upsert_many(self, items) -> None:
        for item in items:
            existing = self.db.query(Pricing).filter(Pricing.model == item.model).one_or_none()
            if existing is None:
                self.db.add(
                    Pricing(
                        model=item.model,
                        input_per_1k=item.input_per_1k,
                        output_per_1k=item.output_per_1k,
                        cached_per_1k=item.cached_per_1k,
                    )
                )
            else:
                existing.input_per_1k = item.input_per_1k
                existing.output_per_1k = item.output_per_1k
                existing.cached_per_1k = item.cached_per_1k
                self.db.add(existing)
        self.db.flush()


class RequestRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def begin_chat_request(
        self,
        tenant_id,
        model: str,
        request_payload: str,
        *,
        provider_name: str | None = None,
        route_reason: str | None = None,
        cache_status: str | None = None,
    ) -> Request:
        row = Request(
            tenant_id=tenant_id,
            model=model,
            status="in_progress",
            request_payload=request_payload,
            provider_name=provider_name,
            route_reason=route_reason,
            cache_status=cache_status,
        )
        self.db.add(row)
        self.db.flush()
        self.db.refresh(row)
        return row

    def create_in_progress(self, tenant_id, model: str, request_payload: str) -> Request:
        return self.begin_chat_request(tenant_id, model, request_payload)

    def complete_chat_request(
        self,
        row: Request,
        response_payload: str,
        latency_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: float,
        *,
        provider_name: str,
        route_reason: str,
        cache_status: str,
    ) -> None:
        row.status = "completed"
        row.response_payload = response_payload
        row.provider_name = provider_name
        row.route_reason = route_reason
        row.cache_status = cache_status
        row.failure_stage = None
        row.failure_code = None
        row.latency_ms = latency_ms
        row.prompt_tokens = prompt_tokens
        row.completion_tokens = completion_tokens
        row.total_tokens = total_tokens
        row.cost_usd = cost_usd
        row.completed_at = func.now()
        self.db.add(row)

    def mark_completed(
        self,
        row: Request,
        response_payload: str,
        latency_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: float,
    ) -> None:
        self.complete_chat_request(
            row,
            response_payload,
            latency_ms,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            cost_usd,
            provider_name=row.provider_name or "unknown",
            route_reason=row.route_reason or "unknown",
            cache_status=row.cache_status or "bypass",
        )

    def mark_status(
        self,
        row: Request,
        status: RequestStatus,
        *,
        failure_stage: str | None = None,
        failure_code: str | None = None,
    ) -> None:
        row.status = status
        row.failure_stage = failure_stage
        row.failure_code = failure_code
        row.completed_at = func.now()
        self.db.add(row)

    def mark_failed(self, row: Request, *, failure_stage: str, failure_code: str) -> None:
        self.mark_status(row, "failed", failure_stage=failure_stage, failure_code=failure_code)

    def mark_canceled(self, row: Request, *, failure_stage: str = "stream") -> None:
        self.mark_status(row, "canceled", failure_stage=failure_stage, failure_code="client_disconnected")

    def get_request_counts(self, tenant_id: uuid.UUID) -> tuple[int, int, float]:
        return get_request_counts(self.db, tenant_id)


class UsageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record_request_usage(
        self,
        tenant_id: uuid.UUID,
        request_id: uuid.UUID,
        model: str,
        tokens: int,
        cost_usd: float,
    ) -> UsageEvent:
        event = UsageEvent(
            tenant_id=tenant_id,
            request_id=request_id,
            model=model,
            tokens=tokens,
            cost_usd=cost_usd,
        )
        self.db.add(event)
        self.db.flush()
        self.db.refresh(event)
        return event

    def add(
        self,
        tenant_id: uuid.UUID,
        request_id: uuid.UUID,
        model: str,
        tokens: int,
        cost_usd: float,
    ) -> UsageEvent:
        return self.record_request_usage(tenant_id, request_id, model, tokens, cost_usd)

    def daily_totals(self, tenant_id: uuid.UUID) -> tuple[int, float]:
        return get_daily_usage_totals(self.db, tenant_id)
