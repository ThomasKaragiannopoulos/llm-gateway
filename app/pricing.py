PRICING_PER_1K = {
    "gpt-4o": {"input": 0.0025, "output": 0.010, "cached": 0.0},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006, "cached": 0.0},
    "mock-1": {"input": 0.002, "output": 0.002, "cached": 0.0005},
    "mock-2": {"input": 0.006, "output": 0.006, "cached": 0.0},
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


def merge_pricing(
    items_or_defaults: list[dict] | dict[str, float | tuple[float, float]],
    overrides: dict[str, float | tuple[float, float] | None] | None = None,
) -> dict:
    if isinstance(items_or_defaults, list):
        merged = dict(PRICING_PER_1K)
        for item in items_or_defaults:
            model = item["model"]
            merged[model] = {
                "input": float(item.get("input_per_1k", 0.0)),
                "output": float(item.get("output_per_1k", 0.0)),
                "cached": float(item.get("cached_per_1k", 0.0)),
            }
        return merged

    merged = dict(items_or_defaults)
    if not overrides:
        return merged
    for model, value in overrides.items():
        if value is None:
            continue
        merged[model] = value
    return merged
