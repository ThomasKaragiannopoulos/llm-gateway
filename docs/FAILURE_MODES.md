# Failure Modes

This document captures the intended behavior when the gateway is operating under degraded conditions. The goal is not to eliminate every failure, but to make failures explicit, bounded, and observable.

## Failure Matrix

| Scenario | Current behavior | Why | Next production step |
| --- | --- | --- | --- |
| Redis unavailable during rate limiting | Fail closed with `503 rate_limit_unavailable` | Silent bypass would undermine tenant isolation and quotas | Add Redis HA and alerting on dependency readiness |
| Redis unavailable during cache lookup | Cache is bypassed | Cache is an optimization, not a correctness dependency | Track cache bypass rate as a dashboard/SLO signal |
| Corrupt cached payload | Entry is deleted and request recomputed | Serving malformed cached data is worse than a miss | Add background cache integrity metrics if cache volume grows |
| Primary provider timeout or error | Request falls back and increments fallback metrics | Keeps user-visible availability higher while preserving route reason | Add provider-specific timeout budgets and retry classes |
| Primary and fallback both fail | Request is marked failed in storage and bubbles as `500` | Preserves forensic data for debugging and usage reconciliation | Split failure classes into retryable and non-retryable outcomes |
| PostgreSQL unavailable during auth or usage writes | Request fails | Tenant auth and request accounting are correctness-critical | Add connection-pool alerting and migration-safe maintenance procedures |
| Daily token or spend quota exceeded | Reject with `429 quota_exceeded` and remaining-budget headers when possible | Prevents unbounded tenant usage | Add tenant-specific alerting for sustained quota denials |
| Prometheus unavailable | Observability summary endpoint fails its upstream query path | Keeps derived metrics honest instead of fabricating values | Add stale-data handling and timestamp surfacing |

## Why Redis Fails Closed

Rate limiting is part of tenant isolation, not just a performance optimization. If Redis is down and the system silently allows traffic, a noisy tenant can bypass controls exactly when the service is already degraded. Failing closed is harsher in the short term but makes the behavior predictable and safer.

## Why Sync SQLAlchemy Was Kept

The service uses synchronous SQLAlchemy sessions inside async handlers. For the current scope this keeps repository code straightforward and testable. The tradeoff is lower concurrency headroom under heavy DB contention. If this moved beyond laptop-scale or small-host traffic, async sessions would be the next infrastructure-aligned change.

## Reviewer Notes

The intended reading of this file is operational judgment:

- which dependencies are correctness-critical
- which failures are allowed to degrade gracefully
- which failures should stop traffic
- where the next scaling step would be
