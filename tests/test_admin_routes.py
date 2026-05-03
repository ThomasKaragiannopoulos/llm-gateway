from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import create_app


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_bootstrap_endpoint_requires_bootstrap_token(client: TestClient) -> None:
    response = client.post("/v1/admin/bootstrap")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_admin_can_create_and_list_tenants(client: TestClient) -> None:
    create_response = client.post(
        "/v1/admin/tenants",
        headers=_auth_headers("admin-secret"),
        json={"tenant": "beta", "tier": "pro"},
    )
    list_response = client.get("/v1/admin/tenants", headers=_auth_headers("admin-secret"))

    assert create_response.status_code == 200
    assert list_response.status_code == 200
    assert any(item["tenant"] == "beta" for item in list_response.json()["tenants"])


def test_non_admin_cannot_access_admin_endpoints(client: TestClient) -> None:
    response = client.get("/v1/admin/tenants", headers=_auth_headers("a-different-key"))
    assert response.status_code == 401


def test_admin_key_lifecycle_endpoints(client: TestClient) -> None:
    client.post("/v1/admin/tenants", headers=_auth_headers("admin-secret"), json={"tenant": "alpha", "tier": "free"})
    create_response = client.post(
        "/v1/admin/tenants/alpha/keys",
        headers=_auth_headers("admin-secret"),
        json={"name": "cli"},
    )
    verify_response = client.post(
        "/v1/admin/keys/verify",
        headers=_auth_headers("admin-secret"),
        json={"tenant": "alpha", "name": "cli", "api_key": create_response.json()["api_key"]},
    )
    list_response = client.get("/v1/admin/tenants/alpha/keys", headers=_auth_headers("admin-secret"))
    revoke_response = client.post(
        "/v1/admin/tenants/alpha/keys/revoke",
        headers=_auth_headers("admin-secret"),
        json={"name": "cli"},
    )

    assert create_response.status_code == 200
    assert verify_response.json()["matches"] is True
    assert any(item["name"] == "cli" for item in list_response.json()["keys"])
    assert revoke_response.status_code == 200


def test_admin_can_manage_limits_pricing_and_usage(client: TestClient) -> None:
    client.post("/v1/admin/tenants", headers=_auth_headers("admin-secret"), json={"tenant": "omega", "tier": "pro"})
    limits_response = client.post(
        "/v1/admin/limits",
        headers=_auth_headers("admin-secret"),
        json={"tenant": "omega", "token_limit_per_day": 1000, "spend_limit_per_day_usd": 2.5},
    )
    pricing_response = client.put(
        "/v1/admin/pricing",
        headers=_auth_headers("admin-secret"),
        json={"items": [{"model": "gpt-4o-mini", "input_per_1k": 0.15, "output_per_1k": 0.6, "cached_per_1k": 0.075}]},
    )
    pricing_get_response = client.get("/v1/admin/pricing", headers=_auth_headers("admin-secret"))
    usage_response = client.get("/v1/admin/usage/omega", headers=_auth_headers("admin-secret"))

    assert limits_response.status_code == 200
    assert limits_response.json()["token_limit_per_day"] == 1000
    assert pricing_response.status_code == 200
    assert pricing_get_response.json()["items"][0]["model"] == "gpt-4o-mini"
    assert usage_response.json()["requests"] == 0


def test_delete_key_handles_invalid_and_missing_ids(client: TestClient) -> None:
    invalid = client.delete("/v1/admin/keys/not-a-uuid", headers=_auth_headers("admin-secret"))
    missing = client.delete("/v1/admin/keys/00000000-0000-0000-0000-000000000000", headers=_auth_headers("admin-secret"))

    assert invalid.status_code == 400
    assert missing.status_code == 404


def test_observability_summary_aggregates_prometheus_queries(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    values = iter([10.0, 2.0, 10.0, 0.05, 3.0, 1.0, 0.5, 1234.0, 5.5])

    async def fake_prom_query(runtime, query: str) -> float:
        _ = (runtime, query)
        return next(values)

    monkeypatch.setattr("app.routers.admin.prom_query", fake_prom_query)

    response = client.get("/v1/observability/summary", headers=_auth_headers("admin-secret"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_rate_per_s"] == 10.0
    assert payload["error_rate"] == 0.2
    assert payload["cache_hit_rate"] == 0.75
    assert payload["p95_latency_ms"] == 50.0


def test_rotate_admin_respects_flag(runtime) -> None:
    runtime.settings.allow_admin_reset = False

    with TestClient(create_app(runtime=runtime)) as client:
        response = client.post("/v1/admin/rotate", headers=_auth_headers("admin-secret"))

    assert response.status_code == 403
