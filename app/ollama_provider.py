import time
import uuid

import httpx

from app.provider import Provider, ProviderResult
from app.schemas import ChatMessage, ChatRequest, ChatResponse


class OllamaProvider(Provider):
    def __init__(self, base_url: str, timeout_s: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def generate(self, request: ChatRequest) -> ProviderResult:
        payload = {
            "model": request.model,
            "messages": [msg.model_dump() for msg in request.messages],
            "stream": False,
            "options": {},
        }
        if request.temperature is not None:
            payload["options"]["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["options"]["num_predict"] = request.max_tokens

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

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

    async def stream(self, request: ChatRequest):
        raise NotImplementedError


def _estimate_tokens(messages: list[ChatMessage], content: str) -> int:
    text = " ".join([m.content for m in messages]) + " " + content
    return max(1, len(text) // 4)
