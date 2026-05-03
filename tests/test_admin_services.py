from __future__ import annotations

from app.errors import ConflictError, NotFoundError
from app.schemas import PricingItem
from app.services.admin import (
    admin_key_exists,
    admin_status,
    bootstrap_admin_key,
    create_tenant,
    create_tenant_api_key,
    get_pricing_rows,
    list_tenant_keys,
    list_tenants,
    revoke_tenant_key,
    rotate_admin_key,
    set_tenant_limits,
    tenant_usage_summary,
    upsert_pricing,
    verify_tenant_key,
)
from app.services.observability import log_event


def test_bootstrap_and_rotate_admin_key(runtime) -> None:
    runtime.settings.admin_api_key = None
    assert admin_status(runtime) is False

    bootstrapped = bootstrap_admin_key(runtime)
    rotated = rotate_admin_key(runtime)

    assert bootstrapped != rotated
    assert admin_key_exists(runtime) is True


def test_create_tenant_conflict_and_listing(runtime) -> None:
    create_tenant(runtime, "beta", "pro")

    tenants = [tenant.name for tenant in list_tenants(runtime)]
    assert "beta" in tenants

    try:
        create_tenant(runtime, "beta", "pro")
    except ConflictError:
        pass
    else:
        raise AssertionError("expected conflict")


def test_tenant_key_lifecycle(runtime) -> None:
    raw_key = create_tenant_api_key(runtime, "gamma", "ci")
    assert verify_tenant_key(runtime, "gamma", "ci", [raw_key, "mismatch"]) is False

    keys = list_tenant_keys(runtime, "gamma")
    assert any(key.name == "ci" for key in keys)

    from app.auth import candidate_api_key_hashes

    assert verify_tenant_key(runtime, "gamma", "ci", candidate_api_key_hashes(raw_key, runtime.settings.api_key_pepper))
    revoke_tenant_key(runtime, "gamma", "ci")

    keys_after_revoke = list_tenant_keys(runtime, "gamma")
    assert any(key.name == "ci" and not key.active for key in keys_after_revoke)


def test_set_limits_and_usage_summary(runtime) -> None:
    create_tenant(runtime, "delta", "free")
    tenant = set_tenant_limits(runtime, "delta", token_limit_per_day=1000, spend_limit_per_day_usd=1.5)
    assert tenant.token_limit_per_day == 1000
    assert float(tenant.spend_limit_per_day_usd) == 1.5

    requests, tokens, cost = tenant_usage_summary(runtime, "delta")
    assert (requests, tokens, cost) == (0, 0, 0.0)


def test_pricing_round_trip(runtime) -> None:
    payload = [PricingItem(model="gpt-4o-mini", input_per_1k=0.15, output_per_1k=0.6, cached_per_1k=0.075)]
    upsert_pricing(runtime, payload)

    rows = get_pricing_rows(runtime)
    assert any(row.model == "gpt-4o-mini" for row in rows)


def test_missing_tenant_raises(runtime) -> None:
    try:
        list_tenant_keys(runtime, "missing")
    except NotFoundError:
        pass
    else:
        raise AssertionError("expected not found")


def test_log_event_serializes_payload(runtime) -> None:
    records: list[str] = []

    class Recorder:
        def info(self, message: str) -> None:
            records.append(message)

    runtime.logger = Recorder()
    log_event(runtime, "test-event", tenant="acme")

    assert records
    assert '"message":"test-event"' in records[0]
