from __future__ import annotations

from app.bootstrap import create_app
from app.schemas import ChatMessage, ChatRequest
from app.services.providers import cacheable_request, explicit_route


def test_create_app_registers_expected_routes(runtime) -> None:
    app = create_app(runtime=runtime)
    routes = {route.path for route in app.routes}
    assert "/health" in routes
    assert "/ready" in routes
    assert "/v1/chat" in routes
    assert "/v1/admin/status" in routes


def test_cacheable_request_only_allows_deterministic_non_streaming_payloads() -> None:
    payload = ChatRequest(model="mock-1", messages=[ChatMessage(role="user", content="hi")], temperature=0)
    assert cacheable_request(payload) is True
    assert cacheable_request(payload.model_copy(update={"stream": True})) is False
    assert cacheable_request(payload.model_copy(update={"temperature": 0.2})) is False


def test_explicit_route_detects_openai_models() -> None:
    decision = explicit_route("gpt-4o-mini")
    assert decision is not None
    assert decision.provider == "openai"
