from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_ready_reports_dependency_checks(client: TestClient) -> None:
    response = client.get("/ready")
    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["checks"]["redis"] == "ok"


def test_metrics_endpoint_exposes_prometheus(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


@pytest.mark.asyncio
async def test_grafana_health_returns_503_when_dependency_check_fails(client: TestClient, monkeypatch) -> None:
    async def failing_healthcheck(url: str, path: str) -> bool:
        _ = (url, path)
        return False

    monkeypatch.setattr("app.routers.health.healthcheck", failing_healthcheck)

    response = client.get("/health/grafana")

    assert response.status_code == 503
    assert response.json()["status"] == "down"
