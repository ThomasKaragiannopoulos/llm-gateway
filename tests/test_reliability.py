
import asyncio

from app.provider import Provider, ProviderResult
from app.schemas import ChatRequest, ChatResponse, ChatMessage
from app.reliability import CircuitBreaker, ResilientProvider, RetryConfig


class FlakyProvider(Provider):
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def generate(self, request: ChatRequest) -> ProviderResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("fail")
        response = ChatResponse(id="1", model=request.model, created=0, content="ok")
        return ProviderResult(response=response, prompt_tokens=1, completion_tokens=1, total_tokens=2)

    async def stream(self, request: ChatRequest):
        raise RuntimeError("not used")


def test_resilient_provider_retries_and_succeeds():
    provider = FlakyProvider(failures=2)
    resilient = ResilientProvider(
        provider,
        name="primary",
        retry=RetryConfig(max_attempts=3, base_delay_ms=1, max_delay_ms=2),
        circuit_breaker=CircuitBreaker(failure_threshold=10, reset_timeout_s=1),
    )
    request = ChatRequest(model="mock-1", messages=[ChatMessage(role="user", content="hi")])
    result = asyncio.run(resilient.generate(request))
    assert result.response.content == "ok"
    assert provider.calls == 3


def test_resilient_provider_circuit_opens():
    provider = FlakyProvider(failures=10)
    resilient = ResilientProvider(
        provider,
        name="primary",
        retry=RetryConfig(max_attempts=1, base_delay_ms=1, max_delay_ms=2),
        circuit_breaker=CircuitBreaker(failure_threshold=2, reset_timeout_s=60),
    )
    request = ChatRequest(model="mock-1", messages=[ChatMessage(role="user", content="hi")])
    try:
        asyncio.run(resilient.generate(request))
    except RuntimeError:
        pass
    try:
        asyncio.run(resilient.generate(request))
    except RuntimeError:
        pass
