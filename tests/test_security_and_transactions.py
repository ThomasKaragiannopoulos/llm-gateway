from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import legacy_hash_api_key
from app.db.repositories import ApiKeyRepository, TenantRepository
from app.db.session import session_scope


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_session_scope_rolls_back_on_error(runtime) -> None:
    with pytest.raises(RuntimeError):
        with session_scope(runtime.session_factory) as db:
            TenantRepository(db).create("rollback-tenant")
            raise RuntimeError("force rollback")

    with session_scope(runtime.session_factory) as db:
        assert TenantRepository(db).get_by_name("rollback-tenant") is None


def test_legacy_api_key_hashes_still_authenticate(runtime) -> None:
    with session_scope(runtime.session_factory) as db:
        tenant = TenantRepository(db).ensure("legacy")
        ApiKeyRepository(db).add(tenant.id, legacy_hash_api_key("legacy-secret"), name="legacy")

    app = __import__("app.bootstrap", fromlist=["create_app"]).create_app(runtime=runtime)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            headers=_auth_headers("legacy-secret"),
            json={"model": "tenant-default", "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 200


def test_successful_auth_updates_api_key_last_used_at(runtime) -> None:
    app = __import__("app.bootstrap", fromlist=["create_app"]).create_app(runtime=runtime)
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            headers=_auth_headers("admin-secret"),
            json={"model": "tenant-default", "messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 200
    with session_scope(runtime.session_factory) as db:
        admin = TenantRepository(db).ensure_admin()
        api_key = ApiKeyRepository(db).get_active_for_tenant(admin.id)
        assert api_key is not None
        assert api_key.last_used_at is not None


def test_prod_settings_require_pepper_and_non_default_bootstrap_token() -> None:
    from app.config import DEFAULT_BOOTSTRAP_ADMIN_TOKEN, Settings

    with pytest.raises(ValueError):
        Settings(
            allowed_origins=["*"],
            primary_fail_rate=0.0,
            fallback_fail_rate=0.0,
            ollama_url="http://localhost:11434",
            ollama_model="llama3.1:8b",
            openai_api_key="",
            provider_mode="mock",
            health_min_samples=5,
            health_error_threshold=0.5,
            requests_per_minute=60,
            tokens_per_minute=1000,
            redis_url="redis://localhost:6379/0",
            cache_ttl_seconds=300,
            cache_version="v1",
            prometheus_url="http://prometheus:9090",
            grafana_url="http://grafana:3000",
            admin_api_key="",
            api_key_pepper="",
            bootstrap_admin_token=DEFAULT_BOOTSTRAP_ADMIN_TOKEN,
            allow_admin_reset=False,
            environment="prod",
            database_url="sqlite+pysqlite:///tmp-test.db",
        )
