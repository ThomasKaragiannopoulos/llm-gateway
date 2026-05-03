import json
import time
import uuid
from collections.abc import AsyncIterator

import httpx

from app.provider import (
    Provider,
    ProviderRequestError,
    ProviderResult,
    ProviderStreamError,
    StreamChunk,
)
from app.schemas import ChatMessage, ChatRequest, ChatResponse


def _payload(request: ChatRequest, *, stream: bool) -> dict[str, object]:
    options: dict[str, float | int] = {}
    if request.temperature is not None:
        options["temperature"] = request.temperature
    if request.max_tokens is not None:
        options["num_predict"] = request.max_tokens
    return {
        "model": request.model,
        "messages": [msg.model_dump() for msg in request.messages],
        "stream": stream,
        "options": options,
    }


class OllamaProvider(Provider):
    def __init__(self, base_url: str, timeout_s: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def generate(self, request: ChatRequest) -> ProviderResult:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=_payload(request, stream=False))
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderRequestError("Ollama request failed") from exc

        message = data.get("message") or {}
        content = message.get("content", "")
        response = ChatResponse(
            id=str(uuid.uuid4()),
            model=data.get("model", request.model),
            created=int(time.time()),
            content=content,
        )

        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        completion_tokens = int(data.get("eval_count") or 0)
        total_tokens = prompt_tokens + completion_tokens
        if total_tokens == 0:
            total_tokens = _estimate_tokens(request.messages, content)

        return ProviderResult(
            response=response,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=_payload(request, stream=True)) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        message = data.get("message") or {}
                        content = message.get("content") or ""
                        done = bool(data.get("done"))
                        if done:
                            prompt_tokens = int(data.get("prompt_eval_count") or 0)
                            completion_tokens = int(data.get("eval_count") or 0)
                            if prompt_tokens + completion_tokens == 0:
                                completion_tokens = _estimate_tokens(request.messages, content)
                            yield StreamChunk(
                                content=content,
                                done=True,
                                model=data.get("model", request.model),
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                            )
                        else:
                            if content:
                                yield StreamChunk(content=content)
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderStreamError("Ollama stream failed") from exc


def _estimate_tokens(messages: list[ChatMessage], content: str) -> int:
    text = " ".join([m.content for m in messages]) + " " + content
    return max(1, len(text) // 4)
