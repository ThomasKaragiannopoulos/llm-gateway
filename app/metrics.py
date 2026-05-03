from prometheus_client import Counter, Histogram

REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)
TENANT_REQUESTS_TOTAL = Counter(
    "tenant_requests_total",
    "Total requests by tenant and tier",
    ["tenant", "tier"],
)
TENANT_TOKENS_TOTAL = Counter(
    "tenant_tokens_total",
    "Total tokens by tenant and tier",
    ["tenant", "tier"],
)
TENANT_COST_TOTAL = Counter(
    "tenant_cost_total",
    "Total cost in USD by tenant and tier",
    ["tenant", "tier"],
)
RATE_LIMITED_TOTAL = Counter(
    "rate_limited_total",
    "Total requests rate limited",
    ["reason"],
)
FALLBACK_TOTAL = Counter(
    "fallback_total",
    "Total fallbacks",
    ["reason", "from_provider", "to_provider"],
)
QUOTA_DENIED_TOTAL = Counter(
    "quota_denied_total",
    "Total requests denied due to budget/quota",
    ["reason"],
)
TOKENS_TOTAL = Counter(
    "tokens_total",
    "Total tokens processed",
    ["model"],
)
COST_TOTAL = Counter(
    "cost_total",
    "Total cost in USD",
    ["model"],
)
CACHE_HITS_TOTAL = Counter(
    "cache_hits_total",
    "Total cache hits",
    ["tenant", "model"],
)
CACHE_MISSES_TOTAL = Counter(
    "cache_misses_total",
    "Total cache misses",
    ["tenant", "model"],
)
