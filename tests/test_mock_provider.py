import asyncio

from app.mock_provider import MockProvider
from app.schemas import ChatMessage, ChatRequest


def test_mock_provider_generate_returns_response():
    provider = MockProvider(delay_ms=0, fail_rate=0.0)
    request = ChatRequest(model="mock-1", messages=[ChatMessage(role="user", content="hi")])

    result = asyncio.run(provider.generate(request))

    assert result.response.model == "mock-1"
    assert result.total_tokens == result.prompt_tokens + result.completion_tokens


def test_mock_provider_stream_yields_chunks():
    provider = MockProvider(delay_ms=0, fail_rate=0.0)
    request = ChatRequest(model="mock-1", messages=[ChatMessage(role="user", content="hi")])

    async def _collect():
        chunks = []
        async for chunk in provider.stream(request):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_collect())

    assert len(chunks) >= 2
    assert any(c.done for c in chunks)
