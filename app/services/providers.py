from __future__ import annotations

import hashlib
import json

from app.ollama_provider import OllamaProvider
from app.routing import RouteDecision
from app.runtime import AppRuntime
from app.schemas import ChatRequest


def cacheable_request(payload: ChatRequest) -> bool:
    if payload.stream:
        return False
    if payload.temperature not in (None, 0):
        return False
    return True


def cache_key(runtime: AppRuntime, tenant_id: str | None, payload: ChatRequest) -> str:
    body = payload.model_dump()
    body["stream"] = False
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    tenant_part = str(tenant_id or "unknown")
    return f"cache:chat:{runtime.settings.cache_version}:{tenant_part}:{digest}"


def explicit_route(model: str) -> RouteDecision | None:
    if model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3"):
        return RouteDecision(model=model, provider="openai", reason=f"model:{model}")
    if model.startswith("mock"):
        return RouteDecision(model=model, provider="mock", reason="model:mock")
    return None


def estimate_tokens(messages: list, content: str) -> int:
    text = " ".join(getattr(message, "content", "") for message in messages) + " " + content
    return max(1, len(text) // 4)


def format_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def resolve_route(runtime: AppRuntime, tier: str, requested_model: str) -> RouteDecision:
    return explicit_route(requested_model) or runtime.routing_policy.choose(tier, runtime.health_tracker)


def resolve_model_name(runtime: AppRuntime, provider_name: str, default_model: str) -> str:
    provider = runtime.providers.get(provider_name)
    if isinstance(provider, OllamaProvider):
        return runtime.settings.ollama_model
    return default_model
