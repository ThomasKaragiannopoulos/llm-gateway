PRICING_PER_1K = {
    "mock-1": 0.002,
}


def cost_usd(model: str, total_tokens: int) -> float:
    price = PRICING_PER_1K.get(model, 0.0)
    return (total_tokens / 1000) * price
