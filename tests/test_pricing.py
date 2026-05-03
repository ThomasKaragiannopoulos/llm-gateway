from app.pricing import cost_usd


def test_cost_usd_known_model():
    # mock-1: 0.002 per 1k for both prompt and completion
    assert cost_usd("mock-1", 1000, 0) == 0.002


def test_cost_usd_split_prompt_completion():
    # gpt-4o-mini: 0.00015 prompt, 0.0006 completion per 1k
    result = cost_usd("gpt-4o-mini", 1000, 1000)
    assert abs(result - 0.00075) < 1e-9


def test_cost_usd_unknown_model():
    assert cost_usd("unknown", 1000, 0) == 0.0
