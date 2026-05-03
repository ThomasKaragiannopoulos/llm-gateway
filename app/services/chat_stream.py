from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator

from app.db.repositories import RequestRepository, UsageRepository
from app.db.session import session_scope
from app.metrics import FALLBACK_TOTAL
from app.provider import ProviderStreamError, StreamChunk
from app.runtime import AppRuntime
from app.schemas import ChatRequest, ChatResponse
from app.services.chat_shared import (
    StreamingChatExecutionResult,
    StreamingSessionState,
    build_completion_event,
    complete_request_record,
    cost_for_usage,
    estimate_stream_usage,
    log_route_resolution,
    resolve_chat_request,
)
from app.services.contracts import DisconnectChecker, RequestContext
from app.services.observability import log_chat_event
from app.services.providers import format_sse


async def stream_provider_chunks(
    runtime: AppRuntime,
    disconnect_checker: DisconnectChecker,
    state: StreamingSessionState,
    *,
    provider_name: str,
    routed_payload: ChatRequest,
    model_name: str,
) -> AsyncIterator[str | StreamChunk]:
    provider = runtime.providers[provider_name]
    async for chunk in provider.stream(routed_payload):
        if await disconnect_checker():
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
    disconnect_checker: DisconnectChecker,
    state: StreamingSessionState,
    *,
    provider_name: str,
    routed_payload: ChatRequest,
    model_name: str,
) -> AsyncIterator[str]:
    async for chunk in stream_provider_chunks(
        runtime,
        disconnect_checker,
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


async def execute_chat_stream(
    runtime: AppRuntime,
    payload: ChatRequest,
    context: RequestContext,
    disconnect_checker: DisconnectChecker,
) -> StreamingChatExecutionResult:
    started_at = time.perf_counter()
    state = StreamingSessionState(response_id=str(uuid.uuid4()), created=int(time.time()))

    async def event_generator() -> AsyncIterator[str]:
        with session_scope(runtime.session_factory) as db:
            requests = RequestRepository(db)
            usage_repo = UsageRepository(db)
            req_row = None
            resolved = None
            try:
                resolved = resolve_chat_request(runtime, db, payload, context, stream=True)
                log_route_resolution(runtime, resolved)
                state.used_provider = resolved.provider_name
                req_row = requests.begin_chat_request(
                    resolved.tenant.id,
                    resolved.model_name,
                    resolved.routed_payload.model_dump_json(),
                    provider_name=resolved.provider_name,
                    route_reason=resolved.route_reason,
                    cache_status="bypass",
                )

                try:
                    async for chunk in consume_stream(
                        runtime,
                        disconnect_checker,
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
                    log_chat_event(
                        runtime,
                        "provider_stream_failed",
                        context,
                        provider=resolved.provider_name,
                        route_reason=resolved.route_reason,
                    )
                    fallback_provider_name = resolved.fallback_provider_name
                    if fallback_provider_name and not state.content_parts:
                        FALLBACK_TOTAL.labels("primary_error", resolved.provider_name, fallback_provider_name).inc()
                        req_row.provider_name = fallback_provider_name
                        req_row.route_reason = "primary_error"
                        async for chunk in consume_stream(
                            runtime,
                            disconnect_checker,
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
                        requests.mark_canceled(req_row)
                        log_chat_event(runtime, "chat_request_canceled", context, stage="stream")
                    elif state.failed:
                        requests.mark_failed(req_row, failure_stage="stream", failure_code="stream_error")
                        log_chat_event(runtime, "chat_request_failed", context, stage="stream", code="stream_error")

    return StreamingChatExecutionResult(
        body=event_generator(),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Cache": "bypass",
        },
    )
