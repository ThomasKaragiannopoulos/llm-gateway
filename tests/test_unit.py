from app.auth import hash_api_key
from app.pricing import cost_usd, merge_pricing
from app.routing import ProviderHealth, RoutingPolicy


def test_hash_api_key_is_deterministic():
    assert hash_api_key("test-key") == hash_api_key("test-key")


def test_hash_api_key_changes_with_input():
    assert hash_api_key("tenant-a") != hash_api_key("tenant-b")


def test_cost_usd_known_inputs():
    assert cost_usd("mock-1", 1000) == 0.002
    assert cost_usd("mock-2", 500) == 0.003


def test_merge_pricing_applies_overrides():
    merged = merge_pricing(
        {"mock-1": 0.002, "mock-2": 0.006},
        {"mock-2": 0.01, "custom": 0.05, "ignored": None},
    )

    assert merged == {"mock-1": 0.002, "mock-2": 0.01, "custom": 0.05}


def test_provider_health_respects_sample_threshold():
    health = ProviderHealth(window_size=5, min_samples=3)
    health.record("primary", False)
    health.record("primary", False)

    assert health.error_rate("primary") == 0.0

    health.record("primary", True)

    assert health.error_rate("primary") == 2 / 3


def test_routing_policy_falls_back_when_primary_unhealthy():
    health = ProviderHealth(window_size=5, min_samples=1)
    policy = RoutingPolicy(error_rate_threshold=0.5)
    health.record("primary", False)

    decision = policy.choose("free", health)

    assert decision.provider == "fallback"
    assert decision.fallback_provider == "primary"
    assert decision.reason == "primary_unhealthy"


def test_routing_policy_prefers_primary_when_healthy():
    health = ProviderHealth(window_size=5, min_samples=1)
    policy = RoutingPolicy(error_rate_threshold=0.5)
    health.record("primary", True)

    decision = policy.choose("pro", health)

    assert decision.provider == "primary"
    assert decision.model == "mock-2"
    assert decision.fallback_provider == "fallback"
