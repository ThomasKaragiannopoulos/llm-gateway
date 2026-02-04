import json
import logging
import sys
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import func

logger = logging.getLogger("llm-gateway")
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_handler)
logger.propagate = False

from app.db.models import Request as RequestModel
from app.db.models import Tenant, UsageEvent
from app.db.session import get_session
from app.mock_provider import MockProvider
from app.pricing import cost_usd
from app.schemas import ChatRequest, ChatResponse

app = FastAPI(title="llm-gateway")
provider = MockProvider()

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


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    db = get_session()
    req_row = None
    start = time.perf_counter()
    try:
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
