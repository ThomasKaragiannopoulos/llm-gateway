import asyncio
import hashlib
import json
import logging
import os
import sys
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
import httpx
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from redis.asyncio import Redis
from sqlalchemy import func

logger = logging.getLogger("llm-gateway")
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_handler)
logger.propagate = False

from app.db.models import Request as RequestModel
from app.auth import hash_api_key
from app.db.models import AdminAction, ApiKey, Tenant, UsageEvent
from app.db.session import get_session
from app.mock_provider import MockProvider
from app.ollama_provider import OllamaProvider
from app.pricing import cost_usd
from app.provider import StreamChunk
from app.routing import ProviderHealth, RoutingPolicy
from app.schemas import (
    ChatRequest,
    ChatResponse,
    CreateKeyRequest,
    CreateKeyResponse,
    CreateTenantKeyRequest,
    CreateTenantRequest,
    CreateTenantResponse,
    ListTenantKeysResponse,
    ListTenantsResponse,
    RevokeKeyByNameRequest,
    RevokeKeyRequest,
    RevokeKeyResponse,
    LimitsRequest,
    LimitsResponse,
    TenantKeyInfo,
    TenantSummary,
    RotateAdminKeyResponse,
    UsageSummaryResponse,
)

app = FastAPI(title="llm-gateway")
frontend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.isdir(frontend_root):
    app.mount("/static", StaticFiles(directory=frontend_root, html=False), name="frontend-static")
PRIMARY_FAIL_RATE = float(os.getenv("PRIMARY_FAIL_RATE", "0"))
FALLBACK_FAIL_RATE = float(os.getenv("FALLBACK_FAIL_RATE", "0"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
PROVIDER_MODE = os.getenv("PROVIDER_MODE", "mock")
if PROVIDER_MODE == "ollama":
    providers = {
        "primary": OllamaProvider(base_url=OLLAMA_URL),
        "fallback": MockProvider(delay_ms=100, fail_rate=FALLBACK_FAIL_RATE),
    }
else:
    providers = {
        "primary": MockProvider(delay_ms=200, fail_rate=PRIMARY_FAIL_RATE),
        "fallback": MockProvider(delay_ms=100, fail_rate=FALLBACK_FAIL_RATE),
    }
HEALTH_MIN_SAMPLES = int(os.getenv("HEALTH_MIN_SAMPLES", "5"))
HEALTH_ERROR_THRESHOLD = float(os.getenv("HEALTH_ERROR_THRESHOLD", "0.5"))
health_tracker = ProviderHealth(window_size=50, min_samples=HEALTH_MIN_SAMPLES)
routing_policy = RoutingPolicy(error_rate_threshold=HEALTH_ERROR_THRESHOLD)
redis_client: Redis | None = None

REQUESTS_PER_MINUTE = int(os.getenv("REQUESTS_PER_MINUTE", "60"))
TOKENS_PER_MINUTE = int(os.getenv("TOKENS_PER_MINUTE", "1000"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "300"))
CACHE_VERSION = "v1"

REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)
TENANT_REQUESTS_TOTAL = Counter(
    "tenant_requests_total",
    "Total requests by tenant and tier",
    ["tenant", "tier"],
)
TENANT_TOKENS_TOTAL = Counter(
    "tenant_tokens_total",
    "Total tokens by tenant and tier",
    ["tenant", "tier"],
)
TENANT_COST_TOTAL = Counter(
    "tenant_cost_total",
    "Total cost in USD by tenant and tier",
    ["tenant", "tier"],
)
RATE_LIMITED_TOTAL = Counter(
    "rate_limited_total",
    "Total requests rate limited",
    ["reason"],
)
FALLBACK_TOTAL = Counter(
    "fallback_total",
    "Total fallbacks",
    ["reason", "from_provider", "to_provider"],
)
QUOTA_DENIED_TOTAL = Counter(
    "quota_denied_total",
    "Total requests denied due to budget/quota",
    ["reason"],
)
TOKENS_TOTAL = Counter(
    "tokens_total",
    "Total tokens processed",
    ["model"],
)
COST_TOTAL = Counter(
    "cost_total",
    "Total cost in USD",
    ["model"],
)
CACHE_HITS_TOTAL = Counter(
    "cache_hits_total",
    "Total cache hits",
    ["tenant", "model"],
)
CACHE_MISSES_TOTAL = Counter(
    "cache_misses_total",
    "Total cache misses",
    ["tenant", "model"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def frontend_index():
    index_path = os.path.join(frontend_root, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/admin")
def frontend_admin():
    admin_path = os.path.join(frontend_root, "admin.html")
    if os.path.isfile(admin_path):
        return FileResponse(admin_path)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/tenants")
def frontend_tenants():
    tenants_path = os.path.join(frontend_root, "tenants.html")
    if os.path.isfile(tenants_path):
        return FileResponse(tenants_path)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/health/ollama")
async def ollama_health():
    provider = providers.get("primary")
    if not isinstance(provider, OllamaProvider):
        return {"status": "disabled"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{OLLAMA_URL}/api/version")
        if resp.status_code != 200:
            return JSONResponse(status_code=503, content={"status": "down"})
        return {"status": "ok", "version": resp.json().get("version")}


@app.on_event("startup")
async def connect_redis():
    global redis_client
    redis_client = Redis.from_url(REDIS_URL, decode_responses=True)


@app.on_event("shutdown")
async def close_redis():
    global redis_client
    if redis_client is not None:
        await redis_client.close()
        redis_client = None


@app.on_event("startup")
def ensure_admin_key():
    admin_key = os.getenv("ADMIN_API_KEY")
    if not admin_key:
        logger.warning(json.dumps({"message": "admin_key_missing"}))
        return

    db = get_session()
    try:
        admin_tenant = db.query(Tenant).filter(Tenant.name == "admin").one_or_none()
        if admin_tenant is None:
            admin_tenant = Tenant(name="admin")
            db.add(admin_tenant)
            db.commit()
            db.refresh(admin_tenant)

        key_hash = hash_api_key(admin_key)
        existing = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).one_or_none()
        if existing is None:
            named = (
                db.query(ApiKey)
                .filter(ApiKey.tenant_id == admin_tenant.id, ApiKey.name == "admin-env")
                .one_or_none()
            )
            active_admin_keys = (
                db.query(ApiKey)
                .filter(ApiKey.tenant_id == admin_tenant.id, ApiKey.active.is_(True))
                .count()
            )
            if named is None:
                db.add(ApiKey(tenant_id=admin_tenant.id, name="admin-env", key_hash=key_hash, active=True))
                db.commit()
            else:
                if active_admin_keys > 0 and named.key_hash != key_hash:
                    logger.warning(json.dumps({"message": "admin_key_env_mismatch"}))
                else:
                    named.key_hash = key_hash
                    named.active = True
                    db.add(named)
                    db.commit()
    finally:
        db.close()


def _get_admin_tenant_id():
    db = get_session()
    try:
        admin_tenant = db.query(Tenant).filter(Tenant.name == "admin").one_or_none()
        if admin_tenant is None:
            return None
        return admin_tenant.id
    finally:
        db.close()


def _cacheable_request(payload: ChatRequest) -> bool:
    if payload.stream:
        return False
    if payload.temperature not in (None, 0):
        return False
    return True


def _cache_key(tenant_id: str | None, payload: ChatRequest) -> str:
    body = payload.model_dump()
    body["stream"] = False
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    tenant_part = str(tenant_id or "unknown")
    return f"cache:chat:{CACHE_VERSION}:{tenant_part}:{digest}"


def _estimate_tokens(messages: list, content: str) -> int:
    text = " ".join([getattr(m, "content", "") for m in messages]) + " " + content
    return max(1, len(text) // 4)


def _format_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


@app.post("/v1/chat", response_model=ChatResponse)
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

        decision = routing_policy.choose(tenant.tier, health_tracker)
        model_name = decision.model
        if isinstance(providers.get(decision.provider), OllamaProvider):
            model_name = OLLAMA_MODEL
        routed_payload = payload.model_copy(update={"model": model_name})

        cache_status = "bypass"
        cache_key = None
        cache_entry = None
        if redis_client is not None and _cacheable_request(routed_payload):
            cache_key = _cache_key(tenant.id, routed_payload)
            cached_raw = await redis_client.get(cache_key)
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
            provider = providers[decision.provider]
            try:
                result = await provider.generate(routed_payload)
                response_obj = result.response
                health_tracker.record(decision.provider, True)
            except Exception:
                health_tracker.record(decision.provider, False)
                fallback_provider = decision.fallback_provider
                if fallback_provider is None:
                    raise
                FALLBACK_TOTAL.labels("primary_error", decision.provider, fallback_provider).inc()
                provider = providers[fallback_provider]
                used_provider = fallback_provider
                result = await provider.generate(routed_payload)
                response_obj = result.response
                health_tracker.record(fallback_provider, True)
            if decision.reason == "primary_unhealthy" and decision.fallback_provider:
                FALLBACK_TOTAL.labels("primary_unhealthy", decision.fallback_provider, decision.provider).inc()
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
                await redis_client.set(
                    cache_key,
                    json.dumps(cache_payload, separators=(",", ":")),
                    ex=CACHE_TTL_SECONDS,
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
            route_reason = "primary_error" if used_provider != decision.provider else decision.reason
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


@app.post("/v1/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request):
    db = get_session()
    req_row = None
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

    async def _stream_from(provider_name: str, routed_payload: ChatRequest, model_name: str):
        nonlocal done_sent
        provider = providers[provider_name]
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
        nonlocal used_provider, prompt_tokens, completion_tokens, total_tokens, completed, canceled, failed
        req_row = None
        model_name = None
        routed_payload = None
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

            decision = routing_policy.choose(tenant.tier, health_tracker)
            model_name = decision.model
            if isinstance(providers.get(decision.provider), OllamaProvider):
                model_name = OLLAMA_MODEL
            routed_payload = payload.model_copy(update={"model": model_name, "stream": True})
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
                            total_tokens = _estimate_tokens(routed_payload.messages, "".join(content_parts))
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
                        health_tracker.record(decision.provider, True)
                    else:
                        yield chunk
                if not done_sent:
                    total_tokens = _estimate_tokens(routed_payload.messages, "".join(content_parts))
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
                    health_tracker.record(decision.provider, True)
            except asyncio.CancelledError:
                raise
            except Exception:
                health_tracker.record(decision.provider, False)
                fallback_provider = decision.fallback_provider
                if fallback_provider and not content_parts:
                    FALLBACK_TOTAL.labels("primary_error", decision.provider, fallback_provider).inc()
                    used_provider = fallback_provider
                    async for chunk in _stream_from(fallback_provider, routed_payload, model_name):
                        if isinstance(chunk, StreamChunk):
                            if chunk.model:
                                model_name = chunk.model
                            prompt_tokens = int(chunk.prompt_tokens or 0)
                            completion_tokens = int(chunk.completion_tokens or 0)
                            total_tokens = prompt_tokens + completion_tokens
                            if total_tokens == 0:
                                total_tokens = _estimate_tokens(routed_payload.messages, "".join(content_parts))
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
                            health_tracker.record(fallback_provider, True)
                        else:
                            yield chunk
                    if not done_sent:
                        total_tokens = _estimate_tokens(routed_payload.messages, "".join(content_parts))
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
                        health_tracker.record(fallback_provider, True)
                else:
                    failed = True
                    yield _format_sse(
                        {
                            "error": {
                                "code": "stream_error",
                                "message": "Stream failed",
                            }
                        }
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
                    tenant = db.query(Tenant).filter(Tenant.id == req_row.tenant_id).one_or_none()
                    if tenant is not None:
                        TENANT_REQUESTS_TOTAL.labels(tenant.name, tenant.tier).inc()
                        TENANT_TOKENS_TOTAL.labels(tenant.name, tenant.tier).inc(req_row.total_tokens or 0)
                        TENANT_COST_TOTAL.labels(tenant.name, tenant.tier).inc(req_row.cost_usd or 0.0)
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


@app.post("/v1/admin/keys", response_model=CreateKeyResponse)
async def create_key(payload: CreateKeyRequest, request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(request.state.tenant_id) != str(admin_id):
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "message": "Admin only"}})

    raw_key = str(uuid.uuid4())
    key_hash = hash_api_key(raw_key)

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == payload.tenant).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )

        existing = (
            db.query(ApiKey)
            .filter(ApiKey.tenant_id == tenant.id, ApiKey.name == payload.name)
            .one_or_none()
        )
        if existing is not None:
            return JSONResponse(
                status_code=409,
                content={"error": {"code": "conflict", "message": "Key name already exists"}},
            )

        db.add(
            ApiKey(
                tenant_id=tenant.id,
                name=payload.name,
                key_hash=key_hash,
                active=True,
                created_by=request.state.tenant_id,
            )
        )
        _log_admin_action(
            db,
            request.state.tenant_id,
            "create_key",
            "tenant",
            str(tenant.id),
            {"tenant": payload.tenant, "name": payload.name},
        )
        db.commit()
    finally:
        db.close()


def _log_admin_action(
    db,
    actor_tenant_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    metadata: dict | None = None,
):
    if not actor_tenant_id:
        return
    payload = json.dumps(metadata or {}, separators=(",", ":")) if metadata else None
    db.add(
        AdminAction(
            actor_tenant_id=actor_tenant_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_json=payload,
        )
    )


@app.post("/v1/admin/tenants", response_model=CreateTenantResponse)
async def create_tenant(payload: CreateTenantRequest, request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(request.state.tenant_id) != str(admin_id):
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "message": "Admin only"}})

    db = get_session()
    try:
        existing = db.query(Tenant).filter(Tenant.name == payload.tenant).one_or_none()
        if existing is not None:
            return JSONResponse(
                status_code=409,
                content={"error": {"code": "conflict", "message": "Tenant already exists"}},
            )
        tier = payload.tier or "free"
        tenant = Tenant(name=payload.tenant, tier=tier)
        db.add(tenant)
        _log_admin_action(
            db,
            request.state.tenant_id,
            "create_tenant",
            "tenant",
            None,
            {"tenant": payload.tenant, "tier": tier},
        )
        db.commit()
    finally:
        db.close()

    return CreateTenantResponse(tenant=payload.tenant, tier=tier)


@app.get("/v1/admin/tenants", response_model=ListTenantsResponse)
async def list_tenants(request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(request.state.tenant_id) != str(admin_id):
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "message": "Admin only"}})

    db = get_session()
    try:
        tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    finally:
        db.close()

    rows = [
        TenantSummary(
            tenant=t.name,
            tier=t.tier,
            created_at=t.created_at.isoformat() if t.created_at else "",
            token_limit_per_day=t.token_limit_per_day,
            spend_limit_per_day_usd=t.spend_limit_per_day_usd,
        )
        for t in tenants
    ]
    return ListTenantsResponse(tenants=rows)


@app.post("/v1/admin/tenants/{tenant_name}/keys", response_model=CreateKeyResponse)
async def create_tenant_key(tenant_name: str, payload: CreateTenantKeyRequest, request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(request.state.tenant_id) != str(admin_id):
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "message": "Admin only"}})

    raw_key = str(uuid.uuid4())
    key_hash = hash_api_key(raw_key)
    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )
        existing = (
            db.query(ApiKey)
            .filter(ApiKey.tenant_id == tenant.id, ApiKey.name == payload.name)
            .one_or_none()
        )
        if existing is not None:
            return JSONResponse(
                status_code=409,
                content={"error": {"code": "conflict", "message": "Key name already exists"}},
            )
        db.add(
            ApiKey(
                tenant_id=tenant.id,
                name=payload.name,
                key_hash=key_hash,
                active=True,
                created_by=request.state.tenant_id,
            )
        )
        _log_admin_action(
            db,
            request.state.tenant_id,
            "create_key",
            "tenant",
            str(tenant.id),
            {"tenant": tenant_name, "name": payload.name},
        )
        db.commit()
    finally:
        db.close()

    return CreateKeyResponse(tenant=tenant_name, name=payload.name, api_key=raw_key)


@app.get("/v1/admin/tenants/{tenant_name}/keys", response_model=ListTenantKeysResponse)
async def list_tenant_keys(tenant_name: str, request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(request.state.tenant_id) != str(admin_id):
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "message": "Admin only"}})

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )
        keys = (
            db.query(ApiKey)
            .filter(ApiKey.tenant_id == tenant.id)
            .order_by(ApiKey.created_at.desc())
            .all()
        )
    finally:
        db.close()

    masked = [
        TenantKeyInfo(
            key_id=str(k.id),
            name=k.name,
            key_last6=k.key_hash[-6:],
            active=bool(k.active),
            created_at=k.created_at.isoformat() if k.created_at else "",
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
            revoked_at=k.revoked_at.isoformat() if k.revoked_at else None,
            revoked_reason=k.revoked_reason,
        )
        for k in keys
    ]
    return ListTenantKeysResponse(tenant=tenant_name, keys=masked)


@app.post("/v1/admin/keys/revoke", response_model=RevokeKeyResponse)
async def revoke_key(payload: RevokeKeyRequest, request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(request.state.tenant_id) != str(admin_id):
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "message": "Admin only"}})

    key_hash = hash_api_key(payload.api_key)
    db = get_session()
    try:
        api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash, ApiKey.active.is_(True)).one_or_none()
        if api_key is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "API key not found"}},
            )
        api_key.active = False
        api_key.revoked_at = func.now()
        api_key.revoked_reason = payload.reason
        tenant = db.query(Tenant).filter(Tenant.id == api_key.tenant_id).one_or_none()
        db.add(api_key)
        _log_admin_action(
            db,
            request.state.tenant_id,
            "revoke_key",
            "api_key",
            str(api_key.id),
            {"tenant": tenant.name if tenant else None, "reason": payload.reason},
        )
        db.commit()
    finally:
        db.close()

    return RevokeKeyResponse(revoked=True, tenant=(tenant.name if tenant else None))


@app.post("/v1/admin/tenants/{tenant_name}/keys/revoke", response_model=RevokeKeyResponse)
async def revoke_key_by_name(tenant_name: str, payload: RevokeKeyByNameRequest, request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(request.state.tenant_id) != str(admin_id):
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "message": "Admin only"}})

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )
        api_key = (
            db.query(ApiKey)
            .filter(ApiKey.tenant_id == tenant.id, ApiKey.name == payload.name, ApiKey.active.is_(True))
            .one_or_none()
        )
        if api_key is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "API key not found"}},
            )
        api_key.active = False
        api_key.revoked_at = func.now()
        api_key.revoked_reason = payload.reason
        db.add(api_key)
        _log_admin_action(
            db,
            request.state.tenant_id,
            "revoke_key_by_name",
            "api_key",
            str(api_key.id),
            {"tenant": tenant_name, "name": payload.name, "reason": payload.reason},
        )
        db.commit()
    finally:
        db.close()

    return RevokeKeyResponse(revoked=True, tenant=tenant_name)


@app.post("/v1/admin/keys/rotate", response_model=RotateAdminKeyResponse)
async def rotate_admin_key(request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(request.state.tenant_id) != str(admin_id):
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "message": "Admin only"}})

    raw_key = str(uuid.uuid4())
    key_hash = hash_api_key(raw_key)
    db = get_session()
    try:
        admin_tenant = db.query(Tenant).filter(Tenant.id == admin_id).one_or_none()
        if admin_tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Admin tenant missing"}},
            )

        db.query(ApiKey).filter(ApiKey.tenant_id == admin_tenant.id, ApiKey.active.is_(True)).update(
            {"active": False}
        )
        rotation_name = f"admin-rotated-{raw_key.split('-')[0]}"
        db.add(
            ApiKey(
                tenant_id=admin_tenant.id,
                name=rotation_name,
                key_hash=key_hash,
                active=True,
                created_by=request.state.tenant_id,
            )
        )
        _log_admin_action(
            db,
            request.state.tenant_id,
            "rotate_admin_key",
            "tenant",
            str(admin_tenant.id),
            {"name": rotation_name},
        )
        db.commit()
    finally:
        db.close()

    return RotateAdminKeyResponse(admin_api_key=raw_key)

@app.post("/v1/admin/limits", response_model=LimitsResponse)
async def set_limits(payload: LimitsRequest, request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(request.state.tenant_id) != str(admin_id):
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "message": "Admin only"}})

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == payload.tenant).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )

        tenant.token_limit_per_day = payload.token_limit_per_day
        tenant.spend_limit_per_day_usd = payload.spend_limit_per_day_usd
        db.add(tenant)
        _log_admin_action(
            db,
            request.state.tenant_id,
            "set_limits",
            "tenant",
            str(tenant.id),
            {
                "tenant": payload.tenant,
                "token_limit_per_day": payload.token_limit_per_day,
                "spend_limit_per_day_usd": payload.spend_limit_per_day_usd,
            },
        )
        db.commit()
    finally:
        db.close()

    return LimitsResponse(
        tenant=payload.tenant,
        token_limit_per_day=payload.token_limit_per_day,
        spend_limit_per_day_usd=payload.spend_limit_per_day_usd,
    )


@app.post("/v1/admin/health/reset")
async def reset_health(request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(request.state.tenant_id) != str(admin_id):
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "message": "Admin only"}})
    health_tracker.reset()
    return {"status": "ok"}


@app.get("/v1/admin/usage/{tenant_name}", response_model=UsageSummaryResponse)
async def usage_summary(tenant_name: str, request: Request):
    admin_id = _get_admin_tenant_id()
    if admin_id is None or str(request.state.tenant_id) != str(admin_id):
        return JSONResponse(status_code=403, content={"error": {"code": "forbidden", "message": "Admin only"}})

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.name == tenant_name).one_or_none()
        if tenant is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "Tenant not found"}},
            )

        request_count = db.query(func.count(RequestModel.id)).filter(RequestModel.tenant_id == tenant.id).scalar()
        totals = (
            db.query(
                func.coalesce(func.sum(UsageEvent.tokens), 0),
                func.coalesce(func.sum(UsageEvent.cost_usd), 0.0),
            )
            .filter(UsageEvent.tenant_id == tenant.id)
            .one()
        )
    finally:
        db.close()

    return UsageSummaryResponse(
        tenant=tenant_name,
        requests=int(request_count or 0),
        tokens=int(totals[0] or 0),
        cost_usd=float(totals[1] or 0.0),
    )

@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    if request.url.path in {"/health", "/metrics", "/health/ollama"}:
        return await call_next(request)
    if request.url.path in {"/", "/admin", "/tenants"} or request.url.path.startswith("/static"):
        return await call_next(request)

    raw_key = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        raw_key = auth_header.split(" ", 1)[1].strip()
    if not raw_key:
        raw_key = request.headers.get("X-API-Key")

    if not raw_key:
        return JSONResponse(status_code=401, content={"error": {"code": "unauthorized", "message": "Missing API key"}})

    key_hash = hash_api_key(raw_key)
    db = get_session()
    try:
        api_key_row = (
            db.query(ApiKey.id, ApiKey.tenant_id)
            .filter(ApiKey.key_hash == key_hash, ApiKey.active.is_(True))
            .one_or_none()
        )
        if api_key_row is not None:
            db.query(ApiKey).filter(ApiKey.id == api_key_row.id).update({"last_used_at": func.now()})
            db.commit()
    finally:
        db.close()

    if api_key_row is None:
        return JSONResponse(status_code=401, content={"error": {"code": "unauthorized", "message": "Invalid API key"}})

    request.state.tenant_id = api_key_row.tenant_id
    return await call_next(request)


@app.middleware("http")
async def rate_limit_requests(request: Request, call_next):
    if request.url.path in {"/health", "/metrics", "/health/ollama"} or request.url.path.startswith("/v1/admin"):
        return await call_next(request)

    if redis_client is None:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "rate_limit_unavailable", "message": "Redis unavailable"}},
        )

    tenant_id = getattr(request.state, "tenant_id", "unknown")
    minute_bucket = int(time.time() // 60)
    key = f"rl:req:{tenant_id}:{minute_bucket}"

    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, 60)

    if count > REQUESTS_PER_MINUTE:
        retry_after = 60 - int(time.time() % 60)
        RATE_LIMITED_TOTAL.labels("requests_per_minute").inc()
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"error": {"code": "rate_limited", "message": "Request limit exceeded"}},
        )

    token_estimate = 2
    token_key = f"rl:tokens:{tenant_id}:{minute_bucket}"
    token_count = await redis_client.incrby(token_key, token_estimate)
    if token_count == token_estimate:
        await redis_client.expire(token_key, 60)

    if token_count > TOKENS_PER_MINUTE:
        retry_after = 60 - int(time.time() % 60)
        RATE_LIMITED_TOTAL.labels("tokens_per_minute").inc()
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={"error": {"code": "rate_limited", "message": "Token limit exceeded"}},
        )

    return await call_next(request)


@app.middleware("http")
async def quota_limits(request: Request, call_next):
    if request.url.path in {"/health", "/metrics", "/health/ollama"} or request.url.path.startswith("/v1/admin"):
        return await call_next(request)

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        return await call_next(request)

    db = get_session()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).one_or_none()
        if tenant is None:
            return await call_next(request)

        if tenant.token_limit_per_day is None and tenant.spend_limit_per_day_usd is None:
            return await call_next(request)

        today = func.date(func.now())
        totals = (
            db.query(
                func.coalesce(func.sum(UsageEvent.tokens), 0),
                func.coalesce(func.sum(UsageEvent.cost_usd), 0.0),
            )
            .filter(UsageEvent.tenant_id == tenant.id)
            .filter(func.date(UsageEvent.created_at) == today)
            .one()
        )
        tokens_used = int(totals[0] or 0)
        cost_used = float(totals[1] or 0.0)

        warn_headers = {}
        if tenant.token_limit_per_day:
            remaining_tokens = tenant.token_limit_per_day - tokens_used
            warn_headers["X-RateLimit-Tokens-Remaining"] = str(max(remaining_tokens, 0))
            if remaining_tokens <= 0:
                QUOTA_DENIED_TOTAL.labels("token_limit").inc()
                return JSONResponse(
                    status_code=429,
                    headers=warn_headers,
                    content={"error": {"code": "quota_exceeded", "message": "Daily token budget exceeded"}},
                )

        if tenant.spend_limit_per_day_usd:
            remaining_spend = tenant.spend_limit_per_day_usd - cost_used
            warn_headers["X-RateLimit-Spend-Remaining"] = f"{max(remaining_spend, 0):.6f}"
            if remaining_spend <= 0:
                QUOTA_DENIED_TOTAL.labels("spend_limit").inc()
                return JSONResponse(
                    status_code=429,
                    headers=warn_headers,
                    content={"error": {"code": "quota_exceeded", "message": "Daily spend budget exceeded"}},
                )

        response = await call_next(request)
        for k, v in warn_headers.items():
            response.headers[k] = v
        return response
    finally:
        db.close()


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    start = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
    finally:
        elapsed_seconds = time.perf_counter() - start
        payload = {
            "message": "request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": getattr(response, "status_code", None),
            "duration_ms": round(elapsed_seconds * 1000, 2),
            "idempotency_key": idempotency_key,
        }
        logger.info(json.dumps(payload, separators=(",", ":")))

    if response is None:
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Unhandled error"}})

    response.headers["X-Request-Id"] = request_id
    if idempotency_key:
        response.headers["Idempotency-Key"] = idempotency_key

    status_code = str(getattr(response, "status_code", 500))
    REQUESTS_TOTAL.labels(request.method, request.url.path, status_code).inc()
    REQUEST_LATENCY.labels(request.method, request.url.path).observe(elapsed_seconds)
    return response
