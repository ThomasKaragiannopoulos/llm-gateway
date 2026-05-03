from __future__ import annotations

import json

import httpx

from app.runtime import AppRuntime


async def healthcheck(url: str, path: str) -> bool:
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get(f"{url}{path}")
        except httpx.HTTPError:
            return False
        return resp.status_code == 200


async def prom_query(runtime: AppRuntime, query: str) -> float:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{runtime.settings.prometheus_url}/api/v1/query", params={"query": query})
        resp.raise_for_status()
        payload = resp.json()
    result = payload.get("data", {}).get("result", [])
    if not result:
        return 0.0
    value = result[0].get("value")
    if not value or len(value) < 2:
        return 0.0
    try:
        return float(value[1])
    except (TypeError, ValueError):
        return 0.0


def log_event(runtime: AppRuntime, message: str, **fields) -> None:
    payload = {"message": message, **fields}
    runtime.logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str))


def log_policy_event(runtime: AppRuntime, message: str, context, **fields) -> None:
    payload = {
        "path": context.path,
        "method": context.method,
        "request_id": context.request_id,
        "tenant_id": getattr(context, "tenant_id", None),
        "idempotency_key": getattr(context, "idempotency_key", None),
    }
    payload.update(fields)
    log_event(runtime, message, **payload)


def log_chat_event(runtime: AppRuntime, message: str, context, **fields) -> None:
    log_policy_event(runtime, message, context, **fields)
