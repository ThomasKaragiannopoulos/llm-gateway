from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.runtime import AppRuntime
from app.schemas import ChatRequest, ChatResponse
from app.services.gateway import execute_chat, execute_chat_stream

router = APIRouter(prefix="/v1")


def _runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request, response: Response):
    result = await execute_chat(_runtime(request), payload, request)
    for key, value in result.headers.items():
        response.headers[key] = value
    return result.response


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request):
    return await execute_chat_stream(_runtime(request), payload, request)
