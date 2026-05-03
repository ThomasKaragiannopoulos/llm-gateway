from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from app.ollama_provider import OllamaProvider, _estimate_tokens
from app.openai_provider import OpenAIProvider
from app.provider import ProviderRequestError, ProviderStreamError
from app.schemas import ChatMessage, ChatRequest


class FakeResponse:
    def __init__(self, *, payload=None, status_code: int = 200, lines: list[str] | None = None) -> None:
        self._payload = payload
        self.status_code = status_code
        self._lines = lines or []

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError("bad response", request=response.request, response=response)

    def json(self):
        return self._payload

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


class FakeStreamContext:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    async def __aenter__(self) -> FakeResponse:
        return self.response

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class FakeAsyncClient:
    def __init__(self, *, post_response: FakeResponse | Exception | None = None, stream_response: FakeResponse | Exception | None = None, timeout=None) -> None:
        self.post_response = post_response
        self.stream_response = stream_response
        self.timeout = timeout
        self.calls: list[tuple[str, str, dict | None]] = []

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, headers=None, json=None):
        self.calls.append(("POST", url, json))
        if isinstance(self.post_response, Exception):
            raise self.post_response
        return self.post_response

    def stream(self, method: str, url: str, headers=None, json=None) -> FakeStreamContext:
        self.calls.append((method, url, json))
        if isinstance(self.stream_response, Exception):
            raise self.stream_response
        assert self.stream_response is not None
        return FakeStreamContext(self.stream_response)


def _request(stream: bool = False) -> ChatRequest:
    return ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.1,
        max_tokens=32,
        stream=stream,
    )


def test_openai_generate_maps_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAsyncClient(
        post_response=FakeResponse(
            payload={
                "id": "resp-1",
                "model": "gpt-4o-mini",
                "created": 123,
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
            }
        )
    )
    monkeypatch.setattr("app.openai_provider.httpx.AsyncClient", lambda timeout=None: client)

    result = asyncio.run(OpenAIProvider(api_key="test-key").generate(_request()))

    assert result.response.content == "hi"
    assert result.total_tokens == 12


def test_openai_generate_rejects_missing_api_key() -> None:
    with pytest.raises(ProviderRequestError):
        asyncio.run(OpenAIProvider(api_key="").generate(_request()))


def test_openai_generate_wraps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAsyncClient(post_response=httpx.ConnectError("boom"))
    monkeypatch.setattr("app.openai_provider.httpx.AsyncClient", lambda timeout=None: client)

    with pytest.raises(ProviderRequestError):
        asyncio.run(OpenAIProvider(api_key="test-key").generate(_request()))


def test_openai_stream_yields_content_and_done(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAsyncClient(
        stream_response=FakeResponse(
            lines=[
                'data: {"choices":[{"delta":{"content":"hel"}}],"model":"gpt-4o-mini"}',
                'data: {"choices":[{"delta":{"content":"lo"}}],"model":"gpt-4o-mini"}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":3},"model":"gpt-4o-mini"}',
                "data: [DONE]",
            ]
        )
    )
    monkeypatch.setattr("app.openai_provider.httpx.AsyncClient", lambda timeout=None: client)

    async def _collect():
        provider = OpenAIProvider(api_key="test-key")
        return [chunk async for chunk in provider.stream(_request(stream=True))]

    chunks = asyncio.run(_collect())

    assert [chunk.content for chunk in chunks[:-1]] == ["hel", "lo"]
    assert chunks[-1].done is True
    assert chunks[-1].completion_tokens == 3


def test_openai_stream_wraps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAsyncClient(stream_response=httpx.ConnectError("boom"))
    monkeypatch.setattr("app.openai_provider.httpx.AsyncClient", lambda timeout=None: client)

    async def _run() -> None:
        provider = OpenAIProvider(api_key="test-key")
        async for _ in provider.stream(_request(stream=True)):
            pass

    with pytest.raises(ProviderStreamError):
        asyncio.run(_run())


def test_ollama_generate_uses_fallback_token_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAsyncClient(
        post_response=FakeResponse(
            payload={
                "model": "tinyllama",
                "message": {"content": "fallback tokens"},
                "prompt_eval_count": 0,
                "eval_count": 0,
            }
        )
    )
    monkeypatch.setattr("app.ollama_provider.httpx.AsyncClient", lambda timeout=None: client)

    result = asyncio.run(OllamaProvider(base_url="http://ollama").generate(_request()))

    assert result.response.content == "fallback tokens"
    assert result.total_tokens == _estimate_tokens(_request().messages, "fallback tokens")


def test_ollama_generate_wraps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAsyncClient(post_response=httpx.ConnectError("boom"))
    monkeypatch.setattr("app.ollama_provider.httpx.AsyncClient", lambda timeout=None: client)

    with pytest.raises(ProviderRequestError):
        asyncio.run(OllamaProvider(base_url="http://ollama").generate(_request()))


def test_ollama_stream_yields_done_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAsyncClient(
        stream_response=FakeResponse(
            lines=[
                '{"message":{"content":"hel"},"done":false}',
                '{"message":{"content":"lo"},"done":false}',
                '{"message":{"content":"done"},"done":true,"prompt_eval_count":4,"eval_count":5,"model":"tinyllama"}',
            ]
        )
    )
    monkeypatch.setattr("app.ollama_provider.httpx.AsyncClient", lambda timeout=None: client)

    async def _collect():
        provider = OllamaProvider(base_url="http://ollama")
        return [chunk async for chunk in provider.stream(_request(stream=True))]

    chunks = asyncio.run(_collect())

    assert [chunk.content for chunk in chunks[:-1]] == ["hel", "lo"]
    assert chunks[-1].done is True
    assert chunks[-1].prompt_tokens == 4


def test_ollama_stream_wraps_decode_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAsyncClient(stream_response=FakeResponse(lines=["{not-json"]))
    monkeypatch.setattr("app.ollama_provider.httpx.AsyncClient", lambda timeout=None: client)

    async def _run() -> None:
        provider = OllamaProvider(base_url="http://ollama")
        async for _ in provider.stream(_request(stream=True)):
            pass

    with pytest.raises(ProviderStreamError):
        asyncio.run(_run())
