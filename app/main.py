import json
import logging
import sys
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

logger = logging.getLogger("llm-gateway")
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_handler)
logger.propagate = False

from app.mock_provider import MockProvider
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    return await provider.generate(request)


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
