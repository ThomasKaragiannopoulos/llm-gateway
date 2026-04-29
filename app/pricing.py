# Pricing table: (prompt_per_1k_tokens, completion_per_1k_tokens) in USD
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o":          (0.0025,  0.010),
    "gpt-4o-mini":     (0.00015, 0.0006),
    "gpt-3.5-turbo":   (0.0005,  0.0015),
    # Mock models use a flat rate (prompt == completion)
    "mock-1":          (0.002,   0.002),
    "mock-2":          (0.006,   0.006),
}


def merge_pricing(
    defaults: dict[str, tuple[float, float]],
    overrides: dict[str, tuple[float, float] | None] | None,
) -> dict[str, tuple[float, float]]:
    merged = dict(defaults)
    if not overrides:
        return merged
    for model, rates in overrides.items():
        if rates is None:
            continue
        merged[model] = rates
    return merged


PRICING = merge_pricing(DEFAULT_PRICING, None)


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = PRICING.get(model)
    if not rates:
        return 0.0
    prompt_rate, completion_rate = rates
    return (prompt_tokens / 1000) * prompt_rate + (completion_tokens / 1000) * completion_rate
