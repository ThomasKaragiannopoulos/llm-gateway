# Operations

## Local Stack

1. `docker compose up --build -d`
2. `poetry run alembic upgrade head`
3. `poetry run python scripts/smoke_test.py --base-url http://localhost:8000 --api-key sk-admin-demo`

## Health

- `GET /health` checks liveness.
- `GET /ready` checks runtime readiness and reports dependency state.
- `GET /metrics` exposes Prometheus metrics.

## Security

- `POST /v1/admin/bootstrap` requires `X-Bootstrap-Token`.
- Admin endpoints require an authenticated admin API key.
- `ALLOW_ADMIN_RESET=true` should only be used in development environments.

## SLO Starter Set

- Availability: 99.9% successful `/ready` checks.
- Error budget signal: alert when 5xx ratio exceeds 2% over 5 minutes.
- Latency: alert when p95 request latency exceeds 2 seconds over 10 minutes.
- Capacity: alert when rate limits or quota denials spike unexpectedly.
