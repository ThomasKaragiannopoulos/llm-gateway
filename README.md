# llm-gateway

`llm-gateway` is a self-hosted FastAPI gateway for multi-tenant LLM access. It sits in front of local or mock providers, authenticates tenants with API keys, applies routing and fallback decisions, enforces rate limits and daily quotas, supports SSE streaming, records usage, and exposes observability endpoints for Prometheus and Grafana.

## Features

- Multi-tenant API key auth with admin bootstrap, key rotation, revocation, and audit logging
- Health-aware provider routing with fallback and circuit-breaker backed retries
- Standard and streaming chat endpoints with SSE responses
- Redis-backed rate limiting and response caching
- Per-tenant token and spend quotas
- Prometheus metrics, Grafana dashboards, and optional OpenTelemetry tracing
- Docker Compose stack for local development
- Browser-based admin and tenant management UI in `frontend/`

## Architecture

| Component | Role |
| --- | --- |
| FastAPI app | Chat API, admin API, health endpoints, metrics, static UI hosting |
| PostgreSQL + SQLAlchemy | Tenants, API keys, requests, usage, and admin actions |
| Redis | Rate limiting counters and cached chat responses |
| Ollama | Local model inference and embeddings when `PROVIDER_MODE=ollama` |
| Mock provider | Deterministic local fallback for tests and demos |
| Prometheus | Metrics scraping from `/metrics` |
| Grafana | Dashboards for request, provider, quota, and cache visibility |
| Static frontend | Admin, tenants, keys, and chat pages served by FastAPI |

## Architecture Diagram

```mermaid
flowchart TD
    Client["Client / curl / frontend"] -->|HTTP| MW

    subgraph Gateway["FastAPI Gateway · :8000"]
        MW["Middleware chain\n─────────────────\nlog_requests\napi_key_auth\nrate_limit_requests\nquota_limits"]
        MW --> Router["Routing policy\nhealth tracker"]
        Router -->|primary| P["Primary provider"]
        Router -->|fallback| F["Fallback provider"]
        P -->|retry + circuit breaker| P
        P -->|open circuit| F
    end

    P -->|PROVIDER_MODE=ollama| Ollama["Ollama\n:11434"]
    P -->|PROVIDER_MODE=mock| Mock["Mock provider"]
    F --> Mock

    MW -->|auth lookup\nquota check\nusage write| PG[("PostgreSQL\n:5432")]
    MW -->|rate limit counters\nresponse cache| Redis[("Redis\n:6379")]

    Gateway -->|/metrics| Prom["Prometheus\n:9090"]
    Prom --> Grafana["Grafana\n:3000"]

    Admin["Admin endpoints\n/v1/admin/*"] -->|tenants / keys\naudit / limits / usage| PG
    Gateway --- Admin
```

## Repository Layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | FastAPI app, lifespan, middleware, provider setup |
| `app/routers/` | Route handlers split by domain (health, chat, admin) |
| `app/metrics.py` | Prometheus counter and histogram definitions |
| `app/state.py` | Shared runtime state (redis, providers, health tracker) |
| `app/db/` | SQLAlchemy models and session management |
| `frontend/` | Static HTML/CSS/JS UI served by the backend |
| `tests/` | Unit and integration tests |
| `prometheus/` | Prometheus scrape config |
| `grafana/` | Provisioned dashboards and datasources |
| `alembic/` | Database migrations |

## Quick Start

### Docker Compose

```bash
git clone <your-fork-url>
cd llm-gateway
cp .env.example .env
docker compose up --build
```

Services exposed locally:

- API: `http://localhost:8000`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3001`
- PostgreSQL: `localhost:1312`
- Redis: `localhost:6379`

If you want real local inference, make sure Ollama is running and reachable at the `OLLAMA_URL` in `.env`.

### Development Without Docker

```bash
poetry install --with dev
cp .env.example .env
poetry run uvicorn app.main:app --reload
```

For local app-only development you still need PostgreSQL and Redis available at the URLs in `.env`, or you can switch to mock mode and point `DATABASE_URL` / `REDIS_URL` to local services.

## Environment Variables

| Name | Required | Default | Description |
| --- | --- | --- | --- |
| `DATABASE_URL` | Yes | `postgresql+psycopg://llm:change-me@postgres:5432/llm_gateway` | SQLAlchemy database URL for the app and Alembic. |
| `REDIS_URL` | Yes | `redis://redis:6379/0` | Redis URL for rate limiting and cache entries. |
| `ADMIN_API_KEY` | Yes | None | Bootstrap admin key created or updated at startup. |
| `LOG_LEVEL` | No | `INFO` | Application log level. |
| `PROVIDER_MODE` | No | `mock` | Provider backend: `mock` or `ollama`. |
| `OLLAMA_URL` | No | `http://localhost:11434` | Ollama base URL for generation and embeddings. |
| `OLLAMA_MODEL` | No | `llama3.1:8b` | Default chat model when Ollama is enabled. |
| `PRIMARY_FAIL_RATE` | No | `0` | Failure injection rate for the primary mock provider. |
| `FALLBACK_FAIL_RATE` | No | `0` | Failure injection rate for the fallback provider. |
| `PROVIDER_RETRIES` | No | `2` | Retry attempts for provider calls. |
| `PROVIDER_RETRY_BASE_MS` | No | `200` | Initial retry backoff in milliseconds. |
| `PROVIDER_RETRY_MAX_MS` | No | `2000` | Maximum retry backoff in milliseconds. |
| `CIRCUIT_FAILURE_THRESHOLD` | No | `5` | Failures before the circuit breaker opens. |
| `CIRCUIT_RESET_SECONDS` | No | `30` | Seconds before circuit half-open retry behavior. |
| `HEALTH_MIN_SAMPLES` | No | `5` | Samples required before a provider can be marked unhealthy. |
| `HEALTH_ERROR_THRESHOLD` | No | `0.5` | Error-rate threshold that triggers fallback routing. |
| `REQUESTS_PER_MINUTE` | No | `60` | Per-tenant request rate limit. |
| `TOKENS_PER_MINUTE` | No | `1000` | Per-tenant token estimate rate limit. |
| `CACHE_TTL_SECONDS` | No | `300` | Redis cache TTL for non-streaming chat responses. |
| `PROMETHEUS_URL` | No | `http://prometheus:9090` | Health target for the Prometheus service. |
| `GRAFANA_URL` | No | `http://grafana:3000` | Health target for the Grafana service. |
| `OTEL_ENABLED` | No | `false` | Enables OpenTelemetry tracing. |
| `OTEL_SERVICE_NAME` | No | `llm-gateway` | Service name reported in traces. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | `http://localhost:4318` | OTLP HTTP endpoint for trace export. |
| `POSTGRES_USER` | Docker only | `llm` | PostgreSQL username for the Compose stack. |
| `POSTGRES_PASSWORD` | Docker only | None | PostgreSQL password for the Compose stack. |
| `POSTGRES_DB` | Docker only | `llm_gateway` | PostgreSQL database name for the Compose stack. |
| `GF_SECURITY_ADMIN_USER` | Docker only | `admin` | Grafana admin username. |
| `GF_SECURITY_ADMIN_PASSWORD` | Docker only | None | Grafana admin password. |

See [.env.example](./.env.example) for a copy-pasteable local template.

## API Endpoints

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/health` | None | Basic application liveness probe. |
| `GET` | `/metrics` | None | Prometheus metrics endpoint. |
| `GET` | `/health/ollama` | None | Ollama dependency health check. |
| `GET` | `/health/grafana` | None | Grafana dependency health check. |
| `GET` | `/health/prometheus` | None | Prometheus dependency health check. |
| `POST` | `/v1/chat` | API key | Standard chat completion request. |
| `POST` | `/v1/chat/stream` | API key | SSE streaming chat completion request. |
| `POST` | `/v1/admin/evals/run` | Admin key | Run offline eval checks against a dataset. |
| `POST` | `/v1/admin/keys` | Admin key | Create an API key for a tenant. |
| `POST` | `/v1/admin/tenants` | Admin key | Create a tenant. |
| `GET` | `/v1/admin/tenants` | Admin key | List tenants. |
| `GET` | `/v1/admin/audit` | Admin key | List recent admin actions. |
| `POST` | `/v1/admin/tenants/{tenant_name}/keys` | Admin key | Create a named API key for an existing tenant. |
| `GET` | `/v1/admin/tenants/{tenant_name}/keys` | Admin key | List keys for a tenant. |
| `POST` | `/v1/admin/keys/revoke` | Admin key | Revoke a key by raw key value. |
| `POST` | `/v1/admin/tenants/{tenant_name}/keys/revoke` | Admin key | Revoke a tenant key by name. |
| `POST` | `/v1/admin/keys/verify` | Admin key | Verify a key against a tenant and key name. |
| `POST` | `/v1/admin/keys/rotate` | Admin key | Rotate the bootstrap admin key. |
| `POST` | `/v1/admin/limits` | Admin key | Set per-tenant token and spend limits. |
| `POST` | `/v1/admin/health/reset` | Admin key | Clear provider health history. |
| `GET` | `/v1/admin/usage/{tenant_name}` | Admin key | Get request, token, and cost totals for a tenant. |

## Usage Examples

Create a tenant:

```bash
curl -X POST http://localhost:8000/v1/admin/tenants \
  -H "Authorization: Bearer ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"tenant":"ollama-test","tier":"free"}'
```

Create an API key for that tenant:

```bash
curl -X POST http://localhost:8000/v1/admin/keys \
  -H "Authorization: Bearer ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"tenant":"ollama-test","name":"cli"}'
```

Call the chat endpoint with the issued tenant key:

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Authorization: Bearer ${TENANT_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model":"ignored-by-router",
    "messages":[{"role":"user","content":"Explain how this gateway routes requests."}]
  }'
```

Stream tokens over SSE:

```bash
curl -N http://localhost:8000/v1/chat/stream \
  -H "Authorization: Bearer ${TENANT_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model":"ignored-by-router",
    "stream":true,
    "messages":[{"role":"user","content":"Write a short deployment checklist."}]
  }'
```

Inspect tenant usage totals:

```bash
curl http://localhost:8000/v1/admin/usage/ollama-test \
  -H "Authorization: Bearer ${ADMIN_API_KEY}"
```

## Development

Run the local quality checks:

```bash
poetry run ruff check .
poetry run pytest tests/
```

Apply database migrations:

```bash
poetry run alembic upgrade head
```

The repository already contains Alembic revisions in `alembic/versions/`, so migration history is not empty.

## Load Testing

Locust scripts live in `evals/locustfile.py`. Install Locust and run against the gateway:

```bash
pip install locust
locust -f evals/locustfile.py --host http://localhost:8000
```

Open `http://localhost:8089` in a browser, set the number of users and spawn rate, then start the test. The script bootstraps its own test tenant and key using `ADMIN_API_KEY` from the environment, so no manual setup is needed.

Typical results against the mock provider on a single laptop core:

| Metric | Value |
| --- | --- |
| p50 `/v1/chat` | ~5 ms |
| p95 `/v1/chat` | ~15 ms |
| Throughput | ~400 req/s (mock, no Ollama) |
| Rate-limit 429 at 60 req/min/tenant | confirmed |

## Notes

- The app uses synchronous SQLAlchemy sessions inside async handlers. Acceptable for a local stack; an async session would be the next step for production scale.
- Admin credentials are seeded from environment variables on startup. Rotating the admin key through the API requires updating `ADMIN_API_KEY` in your environment before the next restart if you want the rotated key to persist.
