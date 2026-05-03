from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.bootstrap import create_app, create_runtime
from app.config import Settings
from app.db.base import Base
from app.db.models import Request, Tenant, UsageEvent
from app.runtime import AppRuntime
from app.services.admin import create_tenant_api_key
from tests.conftest import FakeRedis


def _build_runtime(tmp_path, **settings_updates) -> AppRuntime:
    settings_values = {
        "allowed_origins": ["http://localhost:5173"],
        "primary_fail_rate": 0.0,
        "fallback_fail_rate": 0.0,
        "ollama_url": "http://localhost:11434",
        "ollama_model": "tinyllama:latest",
        "openai_api_key": "test-openai-key",
        "provider_mode": "mock",
        "health_min_samples": 1,
        "health_error_threshold": 0.5,
        "requests_per_minute": 20,
        "tokens_per_minute": 100,
        "redis_url": "redis://unused/0",
        "cache_ttl_seconds": 300,
        "cache_version": "test-v1",
        "prometheus_url": "http://prometheus:9090",
        "grafana_url": "http://grafana:3000",
        "admin_api_key": "admin-secret",
        "api_key_pepper": "test-pepper",
        "bootstrap_admin_token": "bootstrap-token-1234",
        "allow_admin_reset": True,
        "environment": "test",
        "database_url": f"sqlite+pysqlite:///{tmp_path / 'gateway.db'}",
    }
    settings_values.update(settings_updates)
    settings = Settings(
        **settings_values,
    )
    runtime = create_runtime(settings)
    engine = runtime.session_factory.kw["bind"]
    Base.metadata.create_all(bind=engine)
    runtime.redis_client = FakeRedis()
    return runtime


def _client(runtime: AppRuntime) -> TestClient:
    return TestClient(create_app(runtime=runtime))


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_post_v1_chat_happy_path(tmp_path) -> None:
    runtime = _build_runtime(tmp_path)
    tenant_api_key = create_tenant_api_key(runtime, "default", "default")

    with _client(runtime) as client:
        response = client.post(
            "/v1/chat",
            headers=_auth_headers(tenant_api_key),
            json={
                "model": "tenant-default",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200
    assert response.json()["content"] == "mock response"
    assert response.headers["X-Provider"] == "primary"
    assert response.headers["X-Cache"] in {"miss", "bypass"}


def test_auth_failure_for_missing_and_invalid_keys(tmp_path) -> None:
    runtime = _build_runtime(tmp_path)
    create_tenant_api_key(runtime, "default", "default")

    with _client(runtime) as client:
        missing = client.post(
            "/v1/chat",
            json={
                "model": "tenant-default",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        invalid = client.post(
            "/v1/chat",
            headers=_auth_headers("invalid-key"),
            json={
                "model": "tenant-default",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["message"] == "Missing API key"
    assert invalid.status_code == 401
    assert invalid.json()["error"]["message"] == "Invalid API key"


def test_rate_limit_response(tmp_path) -> None:
    runtime = _build_runtime(tmp_path, requests_per_minute=1)
    tenant_api_key = create_tenant_api_key(runtime, "default", "default")

    with _client(runtime) as client:
        first = client.post(
            "/v1/chat",
            headers=_auth_headers(tenant_api_key),
            json={
                "model": "tenant-default",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        second = client.post(
            "/v1/chat",
            headers=_auth_headers(tenant_api_key),
            json={
                "model": "tenant-default",
                "messages": [{"role": "user", "content": "hello again"}],
            },
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"


def test_quota_exceeded_response(tmp_path) -> None:
    runtime = _build_runtime(tmp_path)
    tenant_api_key = create_tenant_api_key(runtime, "quota-tenant", "default")

    with runtime.session_factory() as db:
        tenant = db.query(Tenant).filter(Tenant.name == "quota-tenant").one()
        tenant.token_limit_per_day = 1
        tenant.spend_limit_per_day_usd = 1.0
        db.add(tenant)
        now = datetime.now(UTC)
        request_row = Request(
            tenant_id=tenant.id,
            model="mock-1",
            status="completed",
            total_tokens=2,
            cost_usd=0.002,
            created_at=now,
        )
        db.add(request_row)
        db.commit()
        db.refresh(request_row)
        db.add(
            UsageEvent(
                tenant_id=tenant.id,
                request_id=request_row.id,
                model="mock-1",
                tokens=2,
                cost_usd=0.002,
                created_at=now,
            )
        )
        db.commit()

    with _client(runtime) as client:
        response = client.post(
            "/v1/chat",
            headers=_auth_headers(tenant_api_key),
            json={
                "model": "tenant-default",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "quota_exceeded"
