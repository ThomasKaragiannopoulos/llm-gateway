PRICING_PER_1K = {
    "mock-1": {"input": 0.002, "output": 0.002, "cached": 0.0005},
    "tinyllama:latest": {"input": 0.0, "output": 0.0, "cached": 0.0},
    "llama3.1:8b": {"input": 0.0, "output": 0.0, "cached": 0.0},
}


def cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    pricing_map: dict | None = None,
) -> float:
    source = pricing_map if pricing_map is not None else PRICING_PER_1K
    pricing = source.get(model, {"input": 0.0, "output": 0.0, "cached": 0.0})
    return (
        (prompt_tokens / 1000) * pricing["input"]
        + (completion_tokens / 1000) * pricing["output"]
        + (cached_tokens / 1000) * pricing["cached"]
    )


def merge_pricing(items: list[dict]) -> dict:
    merged = dict(PRICING_PER_1K)
    for item in items:
        model = item["model"]
        merged[model] = {
            "input": float(item.get("input_per_1k", 0.0)),
            "output": float(item.get("output_per_1k", 0.0)),
            "cached": float(item.get("cached_per_1k", 0.0)),
        }
    return merged
