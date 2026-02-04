from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas import ChatRequest, ChatResponse


class Provider(ABC):
    @abstractmethod
    async def generate(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    @abstractmethod
    async def stream(self, request: ChatRequest):
        raise NotImplementedError
