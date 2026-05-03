# Kubernetes Example

This directory shows a minimal production-shaped deployment for `llm-gateway`. It is not intended to be a complete platform, but it demonstrates the expected runtime boundaries:

- gateway application deployment
- config separated from secrets
- HTTP service and ingress
- health probes
- Prometheus scrape annotations

The manifests assume PostgreSQL and Redis are provided externally.

## Apply

```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.example.yaml
kubectl apply -f deploy/k8s/deployment.yaml
kubectl apply -f deploy/k8s/service.yaml
kubectl apply -f deploy/k8s/ingress.yaml
```

## Migration Step

Run database migrations before shifting traffic:

```bash
kubectl exec deploy/llm-gateway -n llm-gateway -- poetry run alembic upgrade head
```

In a real deployment this should be handled as a pre-deploy job rather than an interactive step.
