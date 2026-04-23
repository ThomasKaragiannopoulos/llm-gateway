from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_api_key
from app.db.base import Base
from app.db.models import AdminAction, ApiKey, Request, Tenant, UsageEvent


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int | str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.store[key] = value

    async def incr(self, key: str) -> int:
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = value
        return value

    async def incrby(self, key: str, amount: int) -> int:
        value = int(self.store.get(key, 0)) + amount
        self.store[key] = value
        return value

    async def expire(self, key: str, seconds: int):
        return True

    async def close(self):
        return None


class FakeProvider:
    async def generate(self, request):
        from app.provider import ProviderResult
        from app.schemas import ChatResponse

        response = ChatResponse(
            id="chat-test",
            model=request.model,
            created=1,
            content="mock response",
        )
        return ProviderResult(
            response=response,
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        )

    async def stream(self, request):
        if False:
            yield None


def _load_test_app(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Tenant.__table__,
            ApiKey.__table__,
            Request.__table__,
            UsageEvent.__table__,
            AdminAction.__table__,
        ],
    )

    main = importlib.import_module("app.main")

    def get_session():
        return SessionLocal()

    fake_redis = FakeRedis()
    main.get_session = get_session
    main.Redis.from_url = lambda *args, **kwargs: fake_redis
    main.redis_client = fake_redis
    main.providers = {"primary": FakeProvider(), "fallback": FakeProvider()}
    main.health_tracker.reset()
    main.RAG_ENABLED = False

    main.ensure_admin_key()

    return main, SessionLocal, fake_redis


def _seed_api_key(SessionLocal, raw_key: str, tenant_name: str = "default", **limits):
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).one_or_none()
        if tenant is None:
            tenant = Tenant(name=tenant_name, **limits)
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
        db.add(
            ApiKey(
                tenant_id=tenant.id,
                name=f"{tenant_name}-key",
                key_hash=hash_api_key(raw_key),
                active=True,
            )
        )
        db.commit()
        return tenant


def test_post_v1_chat_happy_path(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")
    main, SessionLocal, _ = _load_test_app(tmp_path)
    _seed_api_key(SessionLocal, "tenant-secret")

    with TestClient(main.app) as client:
        response = client.post(
            "/v1/chat",
            headers={"Authorization": "Bearer tenant-secret"},
            json={
                "model": "ignored-by-router",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 200
    assert response.json()["content"] == "mock response"
    assert response.headers["X-Provider"] == "primary"
    assert response.headers["X-Cache"] in {"miss", "bypass"}


def test_auth_failure_for_missing_and_invalid_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")
    main, SessionLocal, _ = _load_test_app(tmp_path)
    _seed_api_key(SessionLocal, "valid-key")

    with TestClient(main.app) as client:
        missing = client.post(
            "/v1/chat",
            json={
                "model": "mock-1",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        invalid = client.post(
            "/v1/chat",
            headers={"Authorization": "Bearer invalid-key"},
            json={
                "model": "mock-1",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["message"] == "Missing API key"
    assert invalid.status_code == 401
    assert invalid.json()["error"]["message"] == "Invalid API key"


def test_rate_limit_response(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")
    main, SessionLocal, fake_redis = _load_test_app(tmp_path)
    _seed_api_key(SessionLocal, "tenant-secret")
    main.REQUESTS_PER_MINUTE = 1
    fake_redis.store.clear()

    with TestClient(main.app) as client:
        first = client.post(
            "/v1/chat",
            headers={"Authorization": "Bearer tenant-secret"},
            json={
                "model": "mock-1",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        second = client.post(
            "/v1/chat",
            headers={"Authorization": "Bearer tenant-secret"},
            json={
                "model": "mock-1",
                "messages": [{"role": "user", "content": "hello again"}],
            },
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"


def test_quota_exceeded_response(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")
    main, SessionLocal, _ = _load_test_app(tmp_path)
    tenant = _seed_api_key(
        SessionLocal,
        "tenant-secret",
        token_limit_per_day=1,
        spend_limit_per_day_usd=1.0,
    )

    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
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

    with TestClient(main.app) as client:
        response = client.post(
            "/v1/chat",
            headers={"Authorization": "Bearer tenant-secret"},
            json={
                "model": "mock-1",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "quota_exceeded"
