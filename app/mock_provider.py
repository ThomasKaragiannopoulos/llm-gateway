import asyncio
import time
import uuid

from app.provider import Provider
from app.schemas import ChatRequest, ChatResponse


class MockProvider(Provider):
    def __init__(self, delay_ms: int = 200) -> None:
        self.delay_ms = delay_ms

    async def generate(self, request: ChatRequest) -> ChatResponse:
        await asyncio.sleep(self.delay_ms / 1000)
        content = "mock response"
        return ChatResponse(
            id=str(uuid.uuid4()),
            model=request.model,
            created=int(time.time()),
            content=content,
        )

    async def stream(self, request: ChatRequest):
        await asyncio.sleep(self.delay_ms / 1000)
        yield "mock "
        await asyncio.sleep(self.delay_ms / 1000)
        yield "response"
