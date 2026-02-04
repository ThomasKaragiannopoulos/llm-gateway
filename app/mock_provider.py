import asyncio
import time
import uuid

from app.provider import Provider, ProviderResult
from app.schemas import ChatRequest, ChatResponse


class MockProvider(Provider):
    def __init__(self, delay_ms: int = 200, fail_rate: float = 0.0) -> None:
        self.delay_ms = delay_ms
        self.fail_rate = fail_rate

    async def generate(self, request: ChatRequest) -> ChatResponse:
        if self.fail_rate > 0:
            import random

            if random.random() < self.fail_rate:
                raise RuntimeError("mock provider failure")
        await asyncio.sleep(self.delay_ms / 1000)
        content = "mock response"
        response = ChatResponse(
            id=str(uuid.uuid4()),
            model=request.model,
            created=int(time.time()),
            content=content,
        )
        prompt_tokens = 1
        completion_tokens = 1
        total_tokens = prompt_tokens + completion_tokens
        return ProviderResult(
            response=response,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    async def stream(self, request: ChatRequest):
        await asyncio.sleep(self.delay_ms / 1000)
        yield "mock "
        await asyncio.sleep(self.delay_ms / 1000)
        yield "response"
