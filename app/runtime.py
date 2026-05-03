from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field

from redis.asyncio import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.session import build_session_factory
from app.mock_provider import MockProvider
from app.ollama_provider import OllamaProvider
from app.openai_provider import OpenAIProvider
from app.provider import Provider
from app.routing import ProviderHealth, RoutingPolicy


def build_logger() -> logging.Logger:
    logger = logging.getLogger("llm-gateway")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def build_providers(settings: Settings) -> dict[str, Provider]:
    if settings.provider_mode == "ollama":
        return {
            "primary": OllamaProvider(base_url=settings.ollama_url),
            "fallback": MockProvider(delay_ms=100, fail_rate=settings.fallback_fail_rate),
            "mock": MockProvider(delay_ms=100),
            "openai": OpenAIProvider(api_key=settings.openai_api_key),
        }
    return {
        "primary": MockProvider(delay_ms=200, fail_rate=settings.primary_fail_rate),
        "fallback": MockProvider(delay_ms=100, fail_rate=settings.fallback_fail_rate),
        "mock": MockProvider(delay_ms=100),
        "openai": OpenAIProvider(api_key=settings.openai_api_key),
    }


@dataclass
class AppRuntime:
    settings: Settings
    logger: logging.Logger = field(default_factory=build_logger)
    providers: dict[str, Provider] = field(init=False)
    health_tracker: ProviderHealth = field(init=False)
    routing_policy: RoutingPolicy = field(init=False)
    session_factory: sessionmaker[Session] = field(init=False)
    redis_client: Redis | None = None

    def __post_init__(self) -> None:
        self.providers = build_providers(self.settings)
        self.health_tracker = ProviderHealth(window_size=50, min_samples=self.settings.health_min_samples)
        self.routing_policy = RoutingPolicy(error_rate_threshold=self.settings.health_error_threshold)
        self.session_factory = build_session_factory(self.settings.database_url)
