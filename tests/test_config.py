from __future__ import annotations

import pytest

from app.config import Settings


def test_settings_from_env_defaults_are_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOTSTRAP_ADMIN_TOKEN", "bootstrap-token-1234")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///tmp-test.db")
    settings = Settings.from_env()
    assert settings.cache_version
    assert settings.provider_mode == "mock"


def test_settings_reject_invalid_provider_mode() -> None:
    with pytest.raises(ValueError):
        Settings(
            allowed_origins=["*"],
            primary_fail_rate=0.0,
            fallback_fail_rate=0.0,
            ollama_url="http://localhost:11434",
            ollama_model="llama3.1:8b",
            openai_api_key="",
            provider_mode="invalid",
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
            bootstrap_admin_token="bootstrap-token-1234",
            allow_admin_reset=False,
            environment="test",
            database_url="sqlite+pysqlite:///tmp-test.db",
        )
