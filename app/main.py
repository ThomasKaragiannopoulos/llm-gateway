import json
import logging
import os
import sys
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.responses import Response
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
from app.db.models import ApiKey, Tenant, UsageEvent
from app.db.session import get_session
from app.mock_provider import MockProvider
from app.pricing import cost_usd
from app.schemas import (
    ChatRequest,
    ChatResponse,
    CreateKeyRequest,
    CreateKeyResponse,
    LimitsRequest,
    LimitsResponse,
    UsageSummaryResponse,
)

app = FastAPI(title="llm-gateway")
provider = MockProvider()
redis_client: Redis | None = None

REQUESTS_PER_MINUTE = int(os.getenv("REQUESTS_PER_MINUTE", "60"))
TOKENS_PER_MINUTE = int(os.getenv("TOKENS_PER_MINUTE", "1000"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


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
            db.add(ApiKey(tenant_id=admin_tenant.id, key_hash=key_hash, active=True))
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


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
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

        req_row = RequestModel(
            tenant_id=tenant.id,
            model=request.model,
            status="in_progress",
            request_payload=request.model_dump_json(),
        )
        db.add(req_row)
        db.commit()

        response = await provider.generate(request)

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        req_row.status = "completed"
        req_row.response_payload = response.model_dump_json()
        req_row.latency_ms = elapsed_ms
        req_row.prompt_tokens = 1
        req_row.completion_tokens = 1
        req_row.total_tokens = 2
        req_row.cost_usd = cost_usd(request.model, req_row.total_tokens)
        req_row.completed_at = func.now()
        db.add(req_row)
        usage = UsageEvent(
            tenant_id=tenant.id,
            request_id=req_row.id,
            model=request.model,
            tokens=req_row.total_tokens,
            cost_usd=req_row.cost_usd or 0.0,
        )
        db.add(usage)
        db.commit()

        TOKENS_TOTAL.labels(request.model).inc(req_row.total_tokens or 0)
        COST_TOTAL.labels(request.model).inc(req_row.cost_usd or 0.0)
        TENANT_REQUESTS_TOTAL.labels(tenant.name, tenant.tier).inc()
        TENANT_TOKENS_TOTAL.labels(tenant.name, tenant.tier).inc(req_row.total_tokens or 0)
        TENANT_COST_TOTAL.labels(tenant.name, tenant.tier).inc(req_row.cost_usd or 0.0)
        return response
    except Exception:
        if req_row is not None:
            req_row.status = "failed"
            req_row.completed_at = func.now()
            db.add(req_row)
            db.commit()
        raise
    finally:
        db.close()


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
            tenant = Tenant(name=payload.tenant)
            db.add(tenant)
            db.commit()
            db.refresh(tenant)

        db.add(ApiKey(tenant_id=tenant.id, key_hash=key_hash, active=True))
        db.commit()
    finally:
        db.close()

    return CreateKeyResponse(tenant=payload.tenant, api_key=raw_key)


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
        db.commit()
    finally:
        db.close()

    return LimitsResponse(
        tenant=payload.tenant,
        token_limit_per_day=payload.token_limit_per_day,
        spend_limit_per_day_usd=payload.spend_limit_per_day_usd,
    )


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
    if request.url.path in {"/health", "/metrics"}:
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
        api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash, ApiKey.active.is_(True)).one_or_none()
    finally:
        db.close()

    if api_key is None:
        return JSONResponse(status_code=401, content={"error": {"code": "unauthorized", "message": "Invalid API key"}})

    request.state.tenant_id = api_key.tenant_id
    return await call_next(request)


@app.middleware("http")
async def rate_limit_requests(request: Request, call_next):
    if request.url.path in {"/health", "/metrics"}:
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
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    idempotency_key = request.headers.get("Idempotency-Key")
    start = time.perf_counter()
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

    response.headers["X-Request-Id"] = request_id
    if idempotency_key:
        response.headers["Idempotency-Key"] = idempotency_key

    status_code = str(getattr(response, "status_code", 500))
    REQUESTS_TOTAL.labels(request.method, request.url.path, status_code).inc()
    REQUEST_LATENCY.labels(request.method, request.url.path).observe(elapsed_seconds)
    return response
