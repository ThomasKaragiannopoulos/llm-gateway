import asyncio
import hashlib
import json
import os
import time
import uuid

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func

from app import state
from app.db.models import Request as RequestModel, Tenant, UsageEvent
from app.db.session import get_session
from app.metrics import (
    CACHE_HITS_TOTAL,
    CACHE_MISSES_TOTAL,
    COST_TOTAL,
    FALLBACK_TOTAL,
    TENANT_COST_TOTAL,
    TENANT_REQUESTS_TOTAL,
    TENANT_TOKENS_TOTAL,
    TOKENS_TOTAL,
)
from app.ollama_provider import OllamaProvider
from app.pricing import cost_usd
from app.provider import StreamChunk
from app.schemas import ChatRequest, ChatResponse

router = APIRouter()

_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
_CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))
_CACHE_VERSION = "v1"


def _cacheable_request(payload: ChatRequest) -> bool:
    if payload.stream:
        return False
    if payload.temperature not in (None, 0):
        return False
    return True


def _cache_key(tenant_id, payload: ChatRequest) -> str:
    body = payload.model_dump()
    body["stream"] = False
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"cache:chat:{_CACHE_VERSION}:{tenant_id or 'unknown'}:{digest}"


def _estimate_tokens(messages: list, content: str) -> int:
    text = " ".join([getattr(m, "content", "") for m in messages]) + " " + content
    return max(1, len(text) // 4)


def _format_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


@router.post("/v1/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request, response: Response):
    db = get_session()
    req_row = None
    start = time.perf_counter()
    try:
        tenant_id = getattr(request.state, "tenant_id", None)
        tenant = None
        if tenant_id is not None:
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).one_or_none()
        if tenant is None:
            tenant = db.query(Tenant).filter(Tenant.name == "default").one_or_none()
            if tenant is None:
                tenant = Tenant(name="default")
                db.add(tenant)
                db.commit()
                db.refresh(tenant)

        decision = state.routing_policy.choose(tenant.tier, state.health_tracker)
        model_name = decision.model
        if isinstance(state.providers.get(decision.provider), OllamaProvider):
            model_name = _OLLAMA_MODEL
        routed_payload = payload.model_copy(update={"model": model_name})

        cache_status = "bypass"
        cache_key = None
        cache_entry = None
        if state.redis_client is not None and _cacheable_request(routed_payload):
            cache_key = _cache_key(tenant.id, routed_payload)
            cached_raw = await state.redis_client.get(cache_key)
            if cached_raw:
                cache_status = "hit"
                CACHE_HITS_TOTAL.labels(tenant.name, model_name).inc()
                cache_entry = json.loads(cached_raw)
            else:
                cache_status = "miss"
                CACHE_MISSES_TOTAL.labels(tenant.name, model_name).inc()

        req_row = RequestModel(
            tenant_id=tenant.id,
            model=model_name,
            status="in_progress",
            request_payload=routed_payload.model_dump_json(),
        )
        db.add(req_row)
        db.commit()
        used_provider = decision.provider
        route_reason = decision.reason
        if cache_entry is not None:
            response_obj = ChatResponse.model_validate(cache_entry["response"])
            prompt_tokens = int(cache_entry.get("prompt_tokens") or 0)
            completion_tokens = int(cache_entry.get("completion_tokens") or 0)
            total_tokens = int(cache_entry.get("total_tokens") or 0)
            cost_value = float(cache_entry.get("cost_usd") or 0.0)
            used_provider = "cache"
            route_reason = "cache_hit"
        else:
            provider = state.providers[decision.provider]
            try:
                result = await provider.generate(routed_payload)
                response_obj = result.response
                state.health_tracker.record(decision.provider, True)
            except Exception:
                state.health_tracker.record(decision.provider, False)
                fallback_provider = decision.fallback_provider
                if fallback_provider is None:
                    raise
                FALLBACK_TOTAL.labels(
                    "primary_error", decision.provider, fallback_provider
                ).inc()
                provider = state.providers[fallback_provider]
                used_provider = fallback_provider
                result = await provider.generate(routed_payload)
                response_obj = result.response
                state.health_tracker.record(fallback_provider, True)
            if decision.reason == "primary_unhealthy" and decision.fallback_provider:
                FALLBACK_TOTAL.labels(
                    "primary_unhealthy", decision.fallback_provider, decision.provider
                ).inc()
            prompt_tokens = result.prompt_tokens
            completion_tokens = result.completion_tokens
            total_tokens = result.total_tokens
            cost_value = cost_usd(model_name, total_tokens)
            if cache_key and cache_status == "miss":
                cache_payload = {
                    "response": response_obj.model_dump(),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "cost_usd": cost_value,
                }
                await state.redis_client.set(
                    cache_key,
                    json.dumps(cache_payload, separators=(",", ":")),
                    ex=_CACHE_TTL_SECONDS,
                )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        req_row.status = "completed"
        req_row.response_payload = response_obj.model_dump_json()
        req_row.latency_ms = elapsed_ms
        req_row.prompt_tokens = prompt_tokens
        req_row.completion_tokens = completion_tokens
        req_row.total_tokens = total_tokens
        req_row.cost_usd = cost_value
        req_row.completed_at = func.now()
        db.add(req_row)
        usage = UsageEvent(
            tenant_id=tenant.id,
            request_id=req_row.id,
            model=model_name,
            tokens=req_row.total_tokens,
            cost_usd=req_row.cost_usd or 0.0,
        )
        db.add(usage)
        db.commit()

        TOKENS_TOTAL.labels(model_name).inc(req_row.total_tokens or 0)
        COST_TOTAL.labels(model_name).inc(req_row.cost_usd or 0.0)
        TENANT_REQUESTS_TOTAL.labels(tenant.name, tenant.tier).inc()
        TENANT_TOKENS_TOTAL.labels(tenant.name, tenant.tier).inc(req_row.total_tokens or 0)
        TENANT_COST_TOTAL.labels(tenant.name, tenant.tier).inc(req_row.cost_usd or 0.0)
        response.headers["X-Model-Chosen"] = model_name
        if route_reason != "cache_hit":
            route_reason = (
                "primary_error"
                if used_provider != decision.provider
                else decision.reason
            )
        response.headers["X-Route-Reason"] = route_reason
        response.headers["X-Provider"] = used_provider
        response.headers["X-Cache"] = cache_status
        return response_obj
    except Exception:
        if req_row is not None:
            req_row.status = "failed"
            req_row.completed_at = func.now()
            db.add(req_row)
            db.commit()
        raise
    finally:
        db.close()


@router.post("/v1/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request):
    db = get_session()
    start = time.perf_counter()
    response_id = str(uuid.uuid4())
    created = int(time.time())
    content_parts: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    used_provider = None
    completed = False
    canceled = False
    failed = False
    done_sent = False
    tenant = None

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is not None:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).one_or_none()
    if tenant is None:
        tenant = db.query(Tenant).filter(Tenant.name == "default").one_or_none()
        if tenant is None:
            tenant = Tenant(name="default")
            db.add(tenant)
            db.commit()
            db.refresh(tenant)

    decision = state.routing_policy.choose(tenant.tier, state.health_tracker)
    model_name = decision.model
    if isinstance(state.providers.get(decision.provider), OllamaProvider):
        model_name = _OLLAMA_MODEL
    routed_payload = payload.model_copy(update={"model": model_name, "stream": True})

    async def _stream_from(provider_name: str, routed_payload: ChatRequest, model_name: str):
        nonlocal done_sent
        provider = state.providers[provider_name]
        async for chunk in provider.stream(routed_payload):
            if await request.is_disconnected():
                raise asyncio.CancelledError()
            if chunk.content:
                content_parts.append(chunk.content)
                yield _format_sse(
                    {
                        "id": response_id,
                        "model": model_name,
                        "created": created,
                        "content": chunk.content,
                        "done": False,
                    }
                )
            if chunk.done:
                done_sent = True
                yield chunk
                return

    async def _event_generator():
        nonlocal \
            used_provider, \
            model_name, \
            prompt_tokens, \
            completion_tokens, \
            total_tokens, \
            tenant, \
            completed, \
            canceled, \
            failed
        req_row = None
        try:
            used_provider = decision.provider

            req_row = RequestModel(
                tenant_id=tenant.id,
                model=model_name,
                status="in_progress",
                request_payload=routed_payload.model_dump_json(),
            )
            db.add(req_row)
            db.commit()

            try:
                async for chunk in _stream_from(decision.provider, routed_payload, model_name):
                    if isinstance(chunk, StreamChunk):
                        used_provider = decision.provider
                        if chunk.model:
                            model_name = chunk.model
                        prompt_tokens = int(chunk.prompt_tokens or 0)
                        completion_tokens = int(chunk.completion_tokens or 0)
                        total_tokens = prompt_tokens + completion_tokens
                        if total_tokens == 0:
                            total_tokens = _estimate_tokens(
                                routed_payload.messages, "".join(content_parts)
                            )
                            completion_tokens = total_tokens
                        yield _format_sse(
                            {
                                "id": response_id,
                                "model": model_name,
                                "created": created,
                                "content": "",
                                "done": True,
                                "usage": {
                                    "prompt_tokens": prompt_tokens,
                                    "completion_tokens": completion_tokens,
                                    "total_tokens": total_tokens,
                                },
                                "provider": used_provider,
                            }
                        )
                        yield "data: [DONE]\n\n"
                        completed = True
                        state.health_tracker.record(decision.provider, True)
                    else:
                        yield chunk
                if not done_sent:
                    total_tokens = _estimate_tokens(
                        routed_payload.messages, "".join(content_parts)
                    )
                    completion_tokens = total_tokens
                    yield _format_sse(
                        {
                            "id": response_id,
                            "model": model_name,
                            "created": created,
                            "content": "",
                            "done": True,
                            "usage": {
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "total_tokens": total_tokens,
                            },
                            "provider": used_provider,
                        }
                    )
                    yield "data: [DONE]\n\n"
                    completed = True
                    state.health_tracker.record(decision.provider, True)
            except asyncio.CancelledError:
                raise
            except Exception:
                state.health_tracker.record(decision.provider, False)
                fallback_provider = decision.fallback_provider
                if fallback_provider and not content_parts:
                    FALLBACK_TOTAL.labels(
                        "primary_error", decision.provider, fallback_provider
                    ).inc()
                    used_provider = fallback_provider
                    async for chunk in _stream_from(fallback_provider, routed_payload, model_name):
                        if isinstance(chunk, StreamChunk):
                            if chunk.model:
                                model_name = chunk.model
                            prompt_tokens = int(chunk.prompt_tokens or 0)
                            completion_tokens = int(chunk.completion_tokens or 0)
                            total_tokens = prompt_tokens + completion_tokens
                            if total_tokens == 0:
                                total_tokens = _estimate_tokens(
                                    routed_payload.messages, "".join(content_parts)
                                )
                                completion_tokens = total_tokens
                            yield _format_sse(
                                {
                                    "id": response_id,
                                    "model": model_name,
                                    "created": created,
                                    "content": "",
                                    "done": True,
                                    "usage": {
                                        "prompt_tokens": prompt_tokens,
                                        "completion_tokens": completion_tokens,
                                        "total_tokens": total_tokens,
                                    },
                                    "provider": used_provider,
                                }
                            )
                            yield "data: [DONE]\n\n"
                            completed = True
                            state.health_tracker.record(fallback_provider, True)
                        else:
                            yield chunk
                    if not done_sent:
                        total_tokens = _estimate_tokens(
                            routed_payload.messages, "".join(content_parts)
                        )
                        completion_tokens = total_tokens
                        yield _format_sse(
                            {
                                "id": response_id,
                                "model": model_name,
                                "created": created,
                                "content": "",
                                "done": True,
                                "usage": {
                                    "prompt_tokens": prompt_tokens,
                                    "completion_tokens": completion_tokens,
                                    "total_tokens": total_tokens,
                                },
                                "provider": used_provider,
                            }
                        )
                        yield "data: [DONE]\n\n"
                        completed = True
                        state.health_tracker.record(fallback_provider, True)
                else:
                    failed = True
                    yield _format_sse(
                        {"error": {"code": "stream_error", "message": "Stream failed"}}
                    )
                    yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            canceled = True
        finally:
            if req_row is not None:
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                req_row.latency_ms = elapsed_ms
                if completed:
                    req_row.status = "completed"
                    req_row.response_payload = ChatResponse(
                        id=response_id,
                        model=(model_name or req_row.model),
                        created=created,
                        content="".join(content_parts),
                    ).model_dump_json()
                    req_row.prompt_tokens = prompt_tokens
                    req_row.completion_tokens = completion_tokens
                    req_row.total_tokens = total_tokens
                    req_row.cost_usd = cost_usd(req_row.model, total_tokens)
                    req_row.completed_at = func.now()
                    db.add(req_row)
                    usage = UsageEvent(
                        tenant_id=req_row.tenant_id,
                        request_id=req_row.id,
                        model=req_row.model,
                        tokens=req_row.total_tokens or 0,
                        cost_usd=req_row.cost_usd or 0.0,
                    )
                    db.add(usage)
                    db.commit()

                    TOKENS_TOTAL.labels(req_row.model).inc(req_row.total_tokens or 0)
                    COST_TOTAL.labels(req_row.model).inc(req_row.cost_usd or 0.0)
                    t = (
                        db.query(Tenant)
                        .filter(Tenant.id == req_row.tenant_id)
                        .one_or_none()
                    )
                    if t is not None:
                        TENANT_REQUESTS_TOTAL.labels(t.name, t.tier).inc()
                        TENANT_TOKENS_TOTAL.labels(t.name, t.tier).inc(req_row.total_tokens or 0)
                        TENANT_COST_TOTAL.labels(t.name, t.tier).inc(req_row.cost_usd or 0.0)
                elif canceled:
                    req_row.status = "canceled"
                    req_row.completed_at = func.now()
                    db.add(req_row)
                    db.commit()
                elif failed:
                    req_row.status = "failed"
                    req_row.completed_at = func.now()
                    db.add(req_row)
                    db.commit()
            db.close()

    stream = StreamingResponse(_event_generator(), media_type="text/event-stream")
    stream.headers["Cache-Control"] = "no-cache"
    stream.headers["X-Accel-Buffering"] = "no"
    stream.headers["X-Cache"] = "bypass"
    return stream
