from app.routing import ProviderHealth, RoutingPolicy


def test_routing_falls_back_when_primary_unhealthy():
    health = ProviderHealth(window_size=3, min_samples=1)
    policy = RoutingPolicy(error_rate_threshold=0.5)

    health.record("primary", False)
    decision = policy.choose("free", health)

    assert decision.provider == "fallback"
    assert decision.reason == "primary_unhealthy"
    assert decision.fallback_provider == "primary"


def test_routing_tier_selects_model():
    health = ProviderHealth(window_size=3, min_samples=1)
    policy = RoutingPolicy(error_rate_threshold=0.5)

    decision = policy.choose("pro", health)

    assert decision.model == "mock-2"
    assert decision.provider == "primary"
    assert decision.fallback_provider == "fallback"
