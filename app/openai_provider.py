from __future__ import annotations

import time
import uuid

from openai import AsyncOpenAI

from app.provider import Provider, ProviderResult, StreamChunk
from app.schemas import ChatRequest, ChatResponse


class OpenAIProvider(Provider):
    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        # Only override base_url when it differs from the OpenAI default
        # (supports Azure OpenAI, proxies, and compatible APIs)
        effective_base_url = (
            base_url
            if base_url and base_url != "https://api.openai.com/v1"
            else None
        )
        self._client = AsyncOpenAI(api_key=api_key, base_url=effective_base_url)

    async def generate(self, request: ChatRequest) -> ProviderResult:
        kwargs: dict = {
            "model": request.model,
            "messages": [m.model_dump() for m in request.messages],
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens

        resp = await self._client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        prompt_tokens = resp.usage.prompt_tokens if resp.usage else 0
        completion_tokens = resp.usage.completion_tokens if resp.usage else 0

        return ProviderResult(
            response=ChatResponse(
                id=resp.id or str(uuid.uuid4()),
                model=resp.model,
                created=resp.created or int(time.time()),
                content=content,
            ),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    async def stream(self, request: ChatRequest):
        kwargs: dict = {
            "model": request.model,
            "messages": [m.model_dump() for m in request.messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens

        last_model = request.model
        stream_resp = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream_resp:
            if chunk.model:
                last_model = chunk.model
            if not chunk.choices:
                # Final usage-only chunk (emitted when stream_options.include_usage=True)
                prompt_tokens = chunk.usage.prompt_tokens if chunk.usage else 0
                completion_tokens = chunk.usage.completion_tokens if chunk.usage else 0
                yield StreamChunk(
                    content="",
                    done=True,
                    model=last_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                return
            delta = chunk.choices[0].delta
            content = delta.content or ""
            if content:
                yield StreamChunk(content=content)
