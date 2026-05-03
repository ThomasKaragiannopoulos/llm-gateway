# Deployment

## Single-Host Shape

This project is intentionally optimized for local development, but the runtime shape maps directly to a small production deployment:

1. Build the API image from `Dockerfile`.
2. Provision PostgreSQL and Redis outside the app host.
3. Inject secrets through the runtime environment or a secret manager.
4. Run `poetry run alembic upgrade head` before serving traffic.
5. Put the API behind a reverse proxy with TLS, request timeouts, and access logs.
6. Scrape `/metrics` with Prometheus and import `grafana/dashboards/llm-gateway.json`.

## Environment Expectations

- `ADMIN_API_KEY`, `BOOTSTRAP_ADMIN_TOKEN`, `API_KEY_PEPPER`, and provider credentials should come from a secret store.
- `DATABASE_URL` and `REDIS_URL` should point at durable, managed services.
- `ALLOW_ADMIN_RESET` should remain disabled outside development.

## Recommended Hardening

- Replace synchronous DB access with async sessions if request concurrency becomes a bottleneck.
- Restrict CORS origins to known frontend hosts.
- Add request authentication and rate-limit behavior checks to synthetic monitoring.
- Reconcile estimated token costs with provider billing if spend controls become financial controls.

## Production-Shaped Example

The repository now includes a small Kubernetes example in `deploy/k8s/` to make the deployment story concrete:

- two gateway replicas behind a service
- readiness and liveness probes
- config separated from secrets
- ingress timeouts for chat and streaming responses
- Prometheus scrape annotations

The example still assumes managed PostgreSQL and Redis. That is deliberate. The gateway should scale independently from stateful dependencies.

## Rollout Notes

1. Build and publish the image used by `deploy/k8s/deployment.yaml`.
2. Replace placeholder secret values before applying manifests.
3. Run migrations before routing traffic to the new version.
4. Verify `/ready`, `/metrics`, and the synthetic smoke test before widening traffic.
5. Alert on readiness failures, elevated fallback rates, and sustained `429` spikes.
