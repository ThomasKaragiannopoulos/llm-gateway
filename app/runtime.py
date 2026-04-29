from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_session as default_get_session
from app.mock_provider import MockProvider
from app.ollama_provider import OllamaProvider
from app.reliability import CircuitBreaker, ResilientProvider, RetryConfig
from app.routing import ProviderHealth, RoutingPolicy


@dataclass
class RuntimeState:
    redis_client: object | None
    providers: dict[str, object]
    health_tracker: ProviderHealth
    routing_policy: RoutingPolicy


_session_factory: Callable[[], Session] = default_get_session


def set_session_factory(factory: Callable[[], Session]) -> None:
    global _session_factory
    _session_factory = factory


def get_session() -> Session:
    return _session_factory()


def _build_retry_config() -> RetryConfig:
    return RetryConfig(
        max_attempts=settings.provider_retries,
        base_delay_ms=settings.provider_retry_base_ms,
        max_delay_ms=settings.provider_retry_max_ms,
    )


def _build_provider(name: str, provider, *, on_error, on_retry, on_circuit_open):
    return ResilientProvider(
        provider,
        name=name,
        retry=_build_retry_config(),
        circuit_breaker=CircuitBreaker(
            failure_threshold=settings.circuit_failure_threshold,
            reset_timeout_s=settings.circuit_reset_seconds,
        ),
        on_error=on_error,
        on_retry=on_retry,
        on_circuit_open=on_circuit_open,
    )


def build_runtime(*, on_error, on_retry, on_circuit_open) -> RuntimeState:
    if settings.provider_mode == "openai":
        from app.openai_provider import OpenAIProvider
        base_providers = {
            "primary": OpenAIProvider(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            ),
            "fallback": MockProvider(delay_ms=100, fail_rate=settings.fallback_fail_rate),
        }
    elif settings.provider_mode == "ollama":
        base_providers = {
            "primary": OllamaProvider(base_url=settings.ollama_url),
            "fallback": MockProvider(delay_ms=100, fail_rate=settings.fallback_fail_rate),
        }
    else:
        base_providers = {
            "primary": MockProvider(delay_ms=200, fail_rate=settings.primary_fail_rate),
            "fallback": MockProvider(delay_ms=100, fail_rate=settings.fallback_fail_rate),
        }

    providers = {
        name: _build_provider(
            name,
            provider,
            on_error=on_error,
            on_retry=on_retry,
            on_circuit_open=on_circuit_open,
        )
        for name, provider in base_providers.items()
    }
    return RuntimeState(
        redis_client=None,
        providers=providers,
        health_tracker=ProviderHealth(
            window_size=50,
            min_samples=settings.health_min_samples,
        ),
        routing_policy=RoutingPolicy(
            error_rate_threshold=settings.health_error_threshold,
        ),
    )


state = build_runtime(on_error=None, on_retry=None, on_circuit_open=None)
_UNSET = object()


def configure_runtime(*, redis_client=_UNSET, providers=_UNSET, health_tracker=_UNSET, routing_policy=_UNSET):
    if redis_client is not _UNSET:
        state.redis_client = redis_client
    if providers is not _UNSET:
        state.providers = providers
    if health_tracker is not _UNSET:
        state.health_tracker = health_tracker
    if routing_policy is not _UNSET:
        state.routing_policy = routing_policy


def initialize_runtime(*, on_error, on_retry, on_circuit_open) -> RuntimeState:
    new_state = build_runtime(
        on_error=on_error,
        on_retry=on_retry,
        on_circuit_open=on_circuit_open,
    )
    configure_runtime(
        redis_client=new_state.redis_client,
        providers=new_state.providers,
        health_tracker=new_state.health_tracker,
        routing_policy=new_state.routing_policy,
    )
    return state
