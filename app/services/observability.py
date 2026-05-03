from __future__ import annotations

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
