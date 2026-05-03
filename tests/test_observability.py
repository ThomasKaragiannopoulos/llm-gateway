from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.observability import healthcheck, prom_query


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError("bad response", request=response.request, response=response)

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, params=None):
        _ = (url, params)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_healthcheck_returns_false_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.observability.httpx.AsyncClient", lambda timeout=5.0: FakeAsyncClient(httpx.ConnectError("boom")))

    assert asyncio.run(healthcheck("http://grafana", "/api/health")) is False


def test_prom_query_returns_zero_for_missing_or_invalid_values(monkeypatch: pytest.MonkeyPatch, runtime) -> None:
    monkeypatch.setattr(
        "app.services.observability.httpx.AsyncClient",
        lambda timeout=5.0: FakeAsyncClient(FakeResponse(payload={"data": {"result": [{"value": [1, "NaN?"]}]}})),
    )

    assert asyncio.run(prom_query(runtime, "up")) == 0.0


def test_prom_query_parses_numeric_result(monkeypatch: pytest.MonkeyPatch, runtime) -> None:
    monkeypatch.setattr(
        "app.services.observability.httpx.AsyncClient",
        lambda timeout=5.0: FakeAsyncClient(FakeResponse(payload={"data": {"result": [{"value": [1, "12.5"]}]}})),
    )

    assert asyncio.run(prom_query(runtime, "up")) == 12.5
