from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.db.repositories import RequestRepository, UsageRepository
from app.db.session import session_scope
from app.metrics import FALLBACK_TOTAL
from app.provider import ProviderStreamError, StreamChunk
from app.runtime import AppRuntime
from app.schemas import ChatRequest, ChatResponse
from app.services.chat_shared import (
    StreamingSessionState,
    build_completion_event,
    complete_request_record,
    cost_for_usage,
    estimate_stream_usage,
    resolve_chat_request,
)
from app.services.providers import format_sse


async def stream_provider_chunks(
    runtime: AppRuntime,
    request: Request,
    state: StreamingSessionState,
    *,
    provider_name: str,
    routed_payload: ChatRequest,
    model_name: str,
) -> AsyncIterator[str | StreamChunk]:
    provider = runtime.providers[provider_name]
    async for chunk in provider.stream(routed_payload):
        if await request.is_disconnected():
            raise asyncio.CancelledError()
        if chunk.content:
            state.content_parts.append(chunk.content)
            yield format_sse(
                {
                    "id": state.response_id,
                    "model": model_name,
                    "created": state.created,
                    "content": chunk.content,
                    "done": False,
                }
            )
        if chunk.done:
            state.done_sent = True
            yield chunk
            return


async def emit_stream_completion(
    runtime: AppRuntime,
    state: StreamingSessionState,
    *,
    provider_name: str,
    routed_payload: ChatRequest,
    model_name: str,
) -> AsyncIterator[str]:
    usage = estimate_stream_usage(routed_payload, "".join(state.content_parts), state.usage_snapshot())
    state.prompt_tokens = usage.prompt_tokens
    state.completion_tokens = usage.completion_tokens
    state.total_tokens = usage.total_tokens
    state.used_provider = provider_name
    state.completed = True
    yield format_sse(
        build_completion_event(
            response_id=state.response_id,
            model_name=model_name,
            created=state.created,
            usage=usage,
            provider_name=provider_name,
        )
    )
    yield "data: [DONE]\n\n"
    runtime.health_tracker.record(provider_name, True)


async def consume_stream(
    runtime: AppRuntime,
    request: Request,
    state: StreamingSessionState,
    *,
    provider_name: str,
    routed_payload: ChatRequest,
    model_name: str,
) -> AsyncIterator[str]:
    async for chunk in stream_provider_chunks(
        runtime,
        request,
        state,
        provider_name=provider_name,
        routed_payload=routed_payload,
        model_name=model_name,
    ):
        if isinstance(chunk, StreamChunk):
            if chunk.model:
                model_name = chunk.model
            state.prompt_tokens = int(chunk.prompt_tokens or 0)
            state.completion_tokens = int(chunk.completion_tokens or 0)
            state.total_tokens = state.prompt_tokens + state.completion_tokens
            async for event in emit_stream_completion(
                runtime,
                state,
                provider_name=provider_name,
                routed_payload=routed_payload,
                model_name=model_name,
            ):
                yield event
        else:
            yield chunk

    if not state.done_sent:
        async for event in emit_stream_completion(
            runtime,
            state,
            provider_name=provider_name,
            routed_payload=routed_payload,
            model_name=model_name,
        ):
            yield event


async def execute_chat_stream(runtime: AppRuntime, payload: ChatRequest, request: Request) -> StreamingResponse:
    started_at = time.perf_counter()
    state = StreamingSessionState(response_id=str(uuid.uuid4()), created=int(time.time()))

    async def event_generator() -> AsyncIterator[str]:
        with session_scope(runtime.session_factory) as db:
            requests = RequestRepository(db)
            usage_repo = UsageRepository(db)
            req_row = None
            resolved = None
            try:
                resolved = resolve_chat_request(runtime, db, payload, request, stream=True)
                state.used_provider = resolved.provider_name
                req_row = requests.create_in_progress(
                    resolved.tenant.id,
                    resolved.model_name,
                    resolved.routed_payload.model_dump_json(),
                )

                try:
                    async for chunk in consume_stream(
                        runtime,
                        request,
                        state,
                        provider_name=resolved.provider_name,
                        routed_payload=resolved.routed_payload,
                        model_name=resolved.model_name,
                    ):
                        yield chunk
                except asyncio.CancelledError:
                    raise
                except ProviderStreamError:
                    runtime.health_tracker.record(resolved.provider_name, False)
                    fallback_provider_name = resolved.fallback_provider_name
                    if fallback_provider_name and not state.content_parts:
                        FALLBACK_TOTAL.labels("primary_error", resolved.provider_name, fallback_provider_name).inc()
                        async for chunk in consume_stream(
                            runtime,
                            request,
                            state,
                            provider_name=fallback_provider_name,
                            routed_payload=resolved.routed_payload,
                            model_name=resolved.model_name,
                        ):
                            yield chunk
                    else:
                        state.failed = True
                        yield format_sse({"error": {"code": "stream_error", "message": "Stream failed"}})
                        yield "data: [DONE]\n\n"
            except asyncio.CancelledError:
                state.canceled = True
            finally:
                if req_row is not None and resolved is not None:
                    if state.completed:
                        response = ChatResponse(
                            id=state.response_id,
                            model=resolved.model_name,
                            created=state.created,
                            content="".join(state.content_parts),
                        )
                        complete_request_record(
                            requests=requests,
                            usage_repo=usage_repo,
                            req_row=req_row,
                            tenant=resolved.tenant,
                            model_name=req_row.model,
                            response=response,
                            usage=state.usage_snapshot(),
                            cost_value=cost_for_usage(db, req_row.model, state.usage_snapshot()),
                            started_at=started_at,
                        )
                    elif state.canceled:
                        requests.mark_status(req_row, "canceled")
                    elif state.failed:
                        requests.mark_status(req_row, "failed")

    stream = StreamingResponse(event_generator(), media_type="text/event-stream")
    stream.headers["Cache-Control"] = "no-cache"
    stream.headers["X-Accel-Buffering"] = "no"
    stream.headers["X-Cache"] = "bypass"
    return stream
