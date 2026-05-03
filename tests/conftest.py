from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.bootstrap import create_app, create_runtime
from app.config import Settings
from app.db.base import Base
from app.runtime import AppRuntime
from app.services.admin import create_tenant_api_key


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        _ = ex
        self.store[key] = value

    async def incr(self, key: str) -> int:
        value = self.counters.get(key, 0) + 1
        self.counters[key] = value
        return value

    async def incrby(self, key: str, amount: int) -> int:
        value = self.counters.get(key, 0) + amount
        self.counters[key] = value
        return value

    async def expire(self, key: str, seconds: int) -> None:
        _ = (key, seconds)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        allowed_origins=["http://localhost:5173"],
        primary_fail_rate=0.0,
        fallback_fail_rate=0.0,
        ollama_url="http://localhost:11434",
        ollama_model="tinyllama:latest",
        openai_api_key="test-openai-key",
        provider_mode="mock",
        health_min_samples=2,
        health_error_threshold=0.5,
        requests_per_minute=20,
        tokens_per_minute=100,
        redis_url="redis://unused/0",
        cache_ttl_seconds=300,
        cache_version="test-v1",
        prometheus_url="http://prometheus:9090",
        grafana_url="http://grafana:3000",
        admin_api_key="admin-secret",
        api_key_pepper="test-pepper",
        bootstrap_admin_token="bootstrap-token-1234",
        allow_admin_reset=True,
        environment="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'gateway.db'}",
    )


@pytest.fixture
def runtime(settings: Settings) -> AppRuntime:
    runtime = create_runtime(settings)
    engine = runtime.session_factory.kw["bind"]
    assert isinstance(engine, Engine)
    Base.metadata.create_all(bind=engine)
    runtime.redis_client = FakeRedis()
    create_tenant_api_key(runtime, "acme", "acme")
    return runtime


@pytest.fixture
def client(runtime: AppRuntime) -> Iterator[TestClient]:
    app = create_app(runtime=runtime)
    with TestClient(app) as test_client:
        yield test_client
