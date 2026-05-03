from __future__ import annotations

from fastapi.testclient import TestClient


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
