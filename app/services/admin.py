from __future__ import annotations

import json
import uuid

from app.auth import hash_api_key
from app.db.repositories import (
    ApiKeyRepository,
    PricingRepository,
    RequestRepository,
    TenantRepository,
    parse_uuid,
)
from app.db.session import session_scope
from app.errors import ConflictError, NotFoundError
from app.runtime import AppRuntime


def ensure_admin_key(runtime: AppRuntime) -> None:
    if not runtime.settings.admin_api_key:
        runtime.logger.warning(json.dumps({"message": "admin_key_missing"}))
        return

    with session_scope(runtime.session_factory) as db:
        tenants = TenantRepository(db)
        keys = ApiKeyRepository(db)
        admin_tenant = tenants.ensure_admin()
        key_hash = hash_api_key(runtime.settings.admin_api_key, runtime.settings.api_key_pepper)
        existing = keys.get_active_by_hash(key_hash)
        if existing is None:
            keys.add(admin_tenant.id, key_hash, name="admin", active=True)
        total_keys, active_keys = keys.count()
        runtime.logger.info(
            json.dumps(
                {
                    "message": "api_keys_count",
                    "sql_total": total_keys,
                    "sql_active": active_keys,
                },
                separators=(",", ":"),
            )
        )


def get_admin_tenant_id(runtime: AppRuntime):
    with session_scope(runtime.session_factory) as db:
        tenant = TenantRepository(db).get_by_name("admin")
        return None if tenant is None else tenant.id


def admin_key_exists(runtime: AppRuntime) -> bool:
    admin_id = get_admin_tenant_id(runtime)
    if admin_id is None:
        return False
    with session_scope(runtime.session_factory) as db:
        existing = ApiKeyRepository(db).get_active_for_tenant(admin_id)
        return existing is not None


def rotate_admin_key(runtime: AppRuntime) -> str:
    raw_key = str(uuid.uuid4())
    key_hash = hash_api_key(raw_key, runtime.settings.api_key_pepper)
    with session_scope(runtime.session_factory) as db:
        tenants = TenantRepository(db)
        keys = ApiKeyRepository(db)
        admin_tenant = tenants.ensure_admin()
        keys.deactivate_for_tenant(admin_tenant.id)
        keys.add(admin_tenant.id, key_hash, name="admin", active=True)
    return raw_key


def admin_status(runtime: AppRuntime) -> bool:
    with session_scope(runtime.session_factory) as db:
        tenants = TenantRepository(db)
        keys = ApiKeyRepository(db)
        admin_tenant = tenants.get_by_name("admin")
        if admin_tenant is None:
            return False
        has_key = keys.get_active_for_tenant(admin_tenant.id)
        return has_key is not None


def bootstrap_admin_key(runtime: AppRuntime) -> str:
    raw_key = str(uuid.uuid4())
    key_hash = hash_api_key(raw_key, runtime.settings.api_key_pepper)
    with session_scope(runtime.session_factory) as db:
        admin_tenant = TenantRepository(db).ensure_admin()
        ApiKeyRepository(db).add(admin_tenant.id, key_hash, name="admin", active=True)
    return raw_key


def create_tenant_api_key(runtime: AppRuntime, tenant_name: str, key_name: str | None = None) -> str:
    raw_key = str(uuid.uuid4())
    key_hash = hash_api_key(raw_key, runtime.settings.api_key_pepper)
    with session_scope(runtime.session_factory) as db:
        tenants = TenantRepository(db)
        keys = ApiKeyRepository(db)
        tenant = tenants.get_by_name(tenant_name) or tenants.create(tenant_name)
        keys.add(tenant.id, key_hash, name=key_name or tenant_name, active=True)
    return raw_key


def get_pricing_rows(runtime: AppRuntime):
    with session_scope(runtime.session_factory) as db:
        return PricingRepository(db).list_all()


def upsert_pricing(runtime: AppRuntime, items) -> None:
    with session_scope(runtime.session_factory) as db:
        PricingRepository(db).upsert_many(items)


def get_key_rows(runtime: AppRuntime):
    with session_scope(runtime.session_factory) as db:
        return ApiKeyRepository(db).list_with_tenants()


def deactivate_key_by_id(runtime: AppRuntime, key_id: str) -> str | None:
    key_uuid = parse_uuid(key_id)
    if key_uuid is None:
        return "invalid"
    with session_scope(runtime.session_factory) as db:
        key = ApiKeyRepository(db).deactivate_by_id(key_uuid)
        if key is None:
            return "missing"
        return None


def assert_tenant_exists(runtime: AppRuntime, tenant_name: str) -> None:
    with session_scope(runtime.session_factory) as db:
        if TenantRepository(db).get_by_name(tenant_name) is None:
            raise NotFoundError("Tenant not found")


def list_tenants(runtime: AppRuntime):
    with session_scope(runtime.session_factory) as db:
        return TenantRepository(db).list_all()


def create_tenant(runtime: AppRuntime, tenant_name: str, tier: str):
    with session_scope(runtime.session_factory) as db:
        tenants = TenantRepository(db)
        existing = tenants.get_by_name(tenant_name)
        if existing is not None:
            raise ConflictError("Tenant already exists")
        return tenants.create(tenant_name, tier=tier)


def list_tenant_keys(runtime: AppRuntime, tenant_name: str):
    with session_scope(runtime.session_factory) as db:
        tenant = TenantRepository(db).get_by_name(tenant_name)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        return list(tenant.api_keys)


def verify_tenant_key(runtime: AppRuntime, tenant_name: str, key_name: str, key_hashes) -> bool:
    with session_scope(runtime.session_factory) as db:
        return ApiKeyRepository(db).matches_any_hash(tenant_name, key_name, key_hashes)


def revoke_tenant_key(runtime: AppRuntime, tenant_name: str, key_name: str):
    with session_scope(runtime.session_factory) as db:
        row = ApiKeyRepository(db).deactivate_active_by_tenant_and_name(tenant_name, key_name)
        if row is None:
            raise NotFoundError("Active key not found")
        return row


def set_tenant_limits(runtime: AppRuntime, tenant_name: str, *, token_limit_per_day, spend_limit_per_day_usd):
    with session_scope(runtime.session_factory) as db:
        tenants = TenantRepository(db)
        tenant = tenants.get_by_name(tenant_name)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        return tenants.update_limits(
            tenant,
            token_limit_per_day=token_limit_per_day,
            spend_limit_per_day_usd=spend_limit_per_day_usd,
        )


def tenant_usage_summary(runtime: AppRuntime, tenant_name: str) -> tuple[int, int, float]:
    with session_scope(runtime.session_factory) as db:
        tenants = TenantRepository(db)
        tenant = tenants.get_by_name(tenant_name)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        return RequestRepository(db).get_request_counts(tenant.id)
