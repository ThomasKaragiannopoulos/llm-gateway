from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.runtime import AppRuntime


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_chat_happy_path_sets_routing_headers(client: TestClient) -> None:
    response = client.post(
        "/v1/chat",
        headers=_auth_headers("admin-secret"),
        json={"model": "tenant-default", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200
    assert response.headers["X-Provider"] == "primary"
    assert response.headers["X-Cache"] in {"miss", "bypass"}
    assert response.json()["content"] == "mock response"


def test_chat_uses_fallback_provider_when_primary_fails(settings: Settings) -> None:
    failing_runtime = AppRuntime(
        settings=settings.model_copy(update={"primary_fail_rate": 1.0, "fallback_fail_rate": 0.0})
    )
    from app.db.base import Base
    from tests.conftest import FakeRedis
    engine = failing_runtime.session_factory.kw["bind"]
    Base.metadata.create_all(bind=engine)
    failing_runtime.redis_client = FakeRedis()
    from app.bootstrap import create_app
    from app.services.admin import create_tenant_api_key

    create_tenant_api_key(failing_runtime, "default", "default")
    app = create_app(runtime=failing_runtime)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            headers=_auth_headers("admin-secret"),
            json={"model": "tenant-default", "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 200
    assert response.headers["X-Provider"] == "fallback"
    assert response.headers["X-Route-Reason"] == "primary_error"


def test_chat_cache_hit_reports_cache_provider(client: TestClient) -> None:
    payload = {"model": "tenant-default", "messages": [{"role": "user", "content": "hello"}]}

    first_response = client.post("/v1/chat", headers=_auth_headers("admin-secret"), json=payload)
    second_response = client.post("/v1/chat", headers=_auth_headers("admin-secret"), json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.headers["X-Provider"] == "cache"
    assert second_response.headers["X-Route-Reason"] == "cache_hit"
    assert second_response.headers["X-Cache"] == "hit"


def test_streaming_chat_returns_done_event(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/stream",
        headers=_auth_headers("admin-secret"),
        json={"model": "mock-1", "messages": [{"role": "user", "content": "hello"}], "stream": True},
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
