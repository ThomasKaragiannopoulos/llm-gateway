DEFAULT_PRICING_PER_1K = {
    "mock-1": 0.002,
    "mock-2": 0.006,
}


def merge_pricing(
    defaults: dict[str, float], overrides: dict[str, float | None] | None
) -> dict[str, float]:
    merged = dict(defaults)
    if not overrides:
        return merged

    for model, price in overrides.items():
        if price is None:
            continue
        merged[model] = float(price)
    return merged


PRICING_PER_1K = merge_pricing(DEFAULT_PRICING_PER_1K, None)


def cost_usd(model: str, total_tokens: int) -> float:
    price = PRICING_PER_1K.get(model, 0.0)
    return (total_tokens / 1000) * price
