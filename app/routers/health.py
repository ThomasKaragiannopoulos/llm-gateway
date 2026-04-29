import os

import httpx
from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import settings
from app.ollama_provider import OllamaProvider
from app.runtime import state

router = APIRouter()

_GRAFANA_URL = os.getenv("GRAFANA_URL", "http://grafana:3000")
_PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")

_frontend_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
)


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/metrics")
def metrics_endpoint():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/health/ollama")
async def ollama_health():
    provider = state.providers.get("primary")
    if not isinstance(provider, OllamaProvider):
        return {"status": "disabled"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{settings.ollama_url}/api/version")
        if resp.status_code != 200:
            return JSONResponse(status_code=503, content={"status": "down"})
        return {"status": "ok", "version": resp.json().get("version")}


@router.get("/health/grafana")
async def grafana_health():
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{_GRAFANA_URL}/api/health")
        except httpx.HTTPError:
            return JSONResponse(status_code=503, content={"status": "down"})
        if resp.status_code != 200:
            return JSONResponse(status_code=503, content={"status": "down"})
        return {"status": "ok"}


@router.get("/health/prometheus")
async def prometheus_health():
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{_PROMETHEUS_URL}/-/healthy")
        except httpx.HTTPError:
            return JSONResponse(status_code=503, content={"status": "down"})
        if resp.status_code != 200:
            return JSONResponse(status_code=503, content={"status": "down"})
        return {"status": "ok"}


@router.get("/")
def frontend_index():
    path = os.path.join(_frontend_root, "index.html")
    if os.path.isfile(path):
        return FileResponse(path)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@router.get("/tenants")
def frontend_tenants():
    path = os.path.join(_frontend_root, "tenants.html")
    if os.path.isfile(path):
        return FileResponse(path)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@router.get("/keys")
def frontend_keys():
    path = os.path.join(_frontend_root, "keys.html")
    if os.path.isfile(path):
        return FileResponse(path)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@router.get("/chat")
def frontend_chat():
    path = os.path.join(_frontend_root, "chat.html")
    if os.path.isfile(path):
        return FileResponse(path)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})
