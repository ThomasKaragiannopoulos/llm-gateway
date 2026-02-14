from app.pricing import cost_usd


def test_cost_usd_known_model():
    assert cost_usd("mock-1", 1000) == 0.002


def test_cost_usd_unknown_model():
    assert cost_usd("unknown", 1000) == 0.0
