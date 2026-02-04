from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RouteDecision:
    model: str
    provider: str
    reason: str
    fallback_provider: str | None = None


class ProviderHealth:
    def __init__(self, window_size: int = 50) -> None:
        self._window_size = window_size
        self._results: dict[str, deque[bool]] = {}

    def record(self, provider: str, success: bool) -> None:
        if provider not in self._results:
            self._results[provider] = deque(maxlen=self._window_size)
        self._results[provider].append(success)

    def error_rate(self, provider: str) -> float:
        results = self._results.get(provider)
        if not results:
            return 0.0
        failures = sum(1 for ok in results if not ok)
        return failures / len(results)


class RoutingPolicy:
    def __init__(self, error_rate_threshold: float = 0.5) -> None:
        self.error_rate_threshold = error_rate_threshold

    def choose(self, tier: str, health: ProviderHealth) -> RouteDecision:
        if tier == "pro":
            model = "mock-2"
            primary = "primary"
            fallback = "fallback"
            reason = "tier:pro"
        else:
            model = "mock-1"
            primary = "primary"
            fallback = "fallback"
            reason = "tier:free"

        if health.error_rate(primary) > self.error_rate_threshold:
            return RouteDecision(model=model, provider=fallback, reason="primary_unhealthy", fallback_provider=primary)

        return RouteDecision(model=model, provider=primary, reason=reason, fallback_provider=fallback)
