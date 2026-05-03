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
from app.schemas import ChatRequest, ChatResponse

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(Provider):
    def __init__(self, api_key: str, timeout_s: float = 60.0) -> None:
        self.api_key = api_key
        self.timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, request: ChatRequest, stream: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": request.model,
            "messages": [msg.model_dump() for msg in request.messages],
            "stream": stream,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        return payload

    async def generate(self, request: ChatRequest) -> ProviderResult:
        if not self.api_key:
            raise ProviderRequestError("OPENAI_API_KEY is not configured")

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(OPENAI_API_URL, headers=self._headers(), json=self._payload(request))
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderRequestError("OpenAI request failed") from exc

        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)

        response = ChatResponse(
            id=data.get("id") or str(uuid.uuid4()),
            model=data.get("model", request.model),
            created=int(data.get("created") or time.time()),
            content=content,
        )
        return ProviderResult(
            response=response,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        if not self.api_key:
            raise ProviderStreamError("OPENAI_API_KEY is not configured")

        prompt_tokens = 0
        completion_tokens = 0

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST", OPENAI_API_URL, headers=self._headers(), json=self._payload(request, stream=True)
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[len("data:"):].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        choice = (data.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content") or ""
                        finish = choice.get("finish_reason")
                        usage = data.get("usage") or {}
                        if usage:
                            prompt_tokens = int(usage.get("prompt_tokens") or 0)
                            completion_tokens = int(usage.get("completion_tokens") or 0)
                        if finish:
                            yield StreamChunk(
                                content=content,
                                done=True,
                                model=data.get("model", request.model),
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                            )
                            return
                        if content:
                            yield StreamChunk(content=content)
        except httpx.HTTPError as exc:
            raise ProviderStreamError("OpenAI stream failed") from exc
