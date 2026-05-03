from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from app.runtime import AppRuntime
from app.schemas import ChatRequest, ChatResponse
from app.services.contracts import RequestContext
from app.services.gateway import execute_chat, execute_chat_stream

router = APIRouter(prefix="/v1")


def _runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime


def _request_context(request: Request) -> RequestContext:
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-Id") or str(uuid.uuid4())
    return RequestContext(
        method=request.method,
        path=request.url.path,
        request_id=request_id,
        tenant_id=getattr(request.state, "tenant_id", None),
        idempotency_key=request.headers.get("Idempotency-Key"),
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request, response: Response):
    result = await execute_chat(_runtime(request), payload, _request_context(request))
    for key, value in result.headers.items():
        response.headers[key] = value
    return result.response


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request):
    result = await execute_chat_stream(
        _runtime(request),
        payload,
        _request_context(request),
        request.is_disconnected,
    )
    response = StreamingResponse(result.body, media_type="text/event-stream")
    for key, value in result.headers.items():
        response.headers[key] = value
    return response
