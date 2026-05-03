from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.schemas import ChatRequest, ChatResponse


@dataclass(frozen=True)
class ProviderResult:
    response: ChatResponse
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class StreamChunk:
    content: str
    done: bool = False
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ProviderError(RuntimeError):
    pass


class ProviderRequestError(ProviderError):
    pass


class ProviderStreamError(ProviderError):
    pass


class Provider(ABC):
    @abstractmethod
    async def generate(self, request: ChatRequest) -> ProviderResult:
        raise NotImplementedError

    @abstractmethod
    def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        raise NotImplementedError
