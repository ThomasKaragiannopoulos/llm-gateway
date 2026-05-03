from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.exceptions import RedisError

from app.ollama_provider import OllamaProvider
from app.runtime import AppRuntime
from app.schemas import ReadyResponse, StatusResponse
from app.services.observability import healthcheck

router = APIRouter()


def _runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime


def _status_payload(status: str) -> JSONResponse:
    return JSONResponse(status_code=503, content=StatusResponse(status=status).model_dump())


@router.get("/health", response_model=StatusResponse)
def health():
    return StatusResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request):
    runtime = _runtime(request)
    checks: dict[str, str] = {"redis": "disabled"}
    try:
        if runtime.redis_client is not None:
            await runtime.redis_client.ping()
            checks["redis"] = "ok"
        return ReadyResponse(status="ok", environment=runtime.settings.environment, checks=checks)
    except RedisError:
        return JSONResponse(
            status_code=503,
            content=ReadyResponse(
                status="down",
                environment=runtime.settings.environment,
                checks={"redis": "down"},
            ).model_dump(),
        )


@router.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/health/grafana")
async def grafana_health(request: Request):
    runtime = _runtime(request)
    if await healthcheck(runtime.settings.grafana_url, "/api/health"):
        return StatusResponse(status="ok")
    return _status_payload("down")


@router.get("/health/prometheus")
async def prometheus_health(request: Request):
    runtime = _runtime(request)
    if await healthcheck(runtime.settings.prometheus_url, "/-/healthy"):
        return StatusResponse(status="ok")
    return _status_payload("down")


@router.get("/health/ollama")
async def ollama_health(request: Request):
    runtime = _runtime(request)
    provider = runtime.providers.get("primary")
    if not isinstance(provider, OllamaProvider):
        return StatusResponse(status="disabled")
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{runtime.settings.ollama_url}/api/version")
        except httpx.HTTPError:
            return _status_payload("down")
        if resp.status_code != 200:
            return _status_payload("down")
        return {"status": "ok", "version": resp.json().get("version")}
