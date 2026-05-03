# Architecture

`llm-gateway` is now organized around a thin FastAPI entrypoint and explicit runtime boundaries.

## Runtime Shape

- `app/main.py` only exposes `app`.
- `app/bootstrap.py` creates the FastAPI app, wires middleware, routers, and lifespan startup/shutdown.
- `app/config.py` is the typed runtime settings boundary.
- `app/runtime.py` owns shared runtime state such as providers, health tracking, routing policy, logger, and Redis.

## Request Lifecycle

1. Middleware assigns request IDs, logs structured request metadata, enforces API key auth, rate limits, and tenant quota limits.
2. Routers stay thin and delegate to services.
3. Services own routing decisions, provider fallback, caching, persistence, and usage accounting.
4. Repositories isolate recurring data access patterns from transport code.

## Module Boundaries

- `app/routers/*`: HTTP-only concerns.
- `app/services/*`: business logic and orchestration.
- `app/db/repositories.py`: storage access helpers.
- `app/metrics.py`: metric definitions.
- `app/provider.py` and provider implementations: provider contracts and adapters.
- `app/services/gateway.py`: thin facade over `chat_sync`, `chat_stream`, and `chat_shared`.

## Refactor Notes

- Middleware path exemptions are defined once and reused across auth, rate limiting, and quota enforcement. This keeps policy drift out of individual middleware functions.
- Chat orchestration is split by responsibility: `chat_sync.py` for request/response execution, `chat_stream.py` for SSE streaming, and `chat_shared.py` for shared state and persistence helpers. The tradeoff is a few more modules in exchange for smaller units with clearer failure boundaries.
- Repositories own recurring state mutations such as key revocation and tenant limit updates. Routers should validate requests and delegate persistence details instead of mutating ORM rows directly.
- Transaction ownership lives in `session_scope()`. Repository methods flush and refresh rows, while the session context commits on success and rolls back on failure. This makes multi-step workflows atomic without pushing transaction logic into every repository method.
- API key verification supports both current PBKDF2-HMAC hashes and legacy SHA-256 hashes for backward compatibility while new keys are stored with the stronger scheme.

## Operational Expectations

- `/health` is a liveness probe.
- `/ready` is a readiness probe and includes runtime dependency checks.
- Redis is initialized during app lifespan startup and closed during shutdown.
- Admin bootstrap and key seeding happen centrally during startup.
