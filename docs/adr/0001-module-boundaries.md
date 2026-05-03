# ADR 0001: Split The Gateway Into Runtime, Router, Service, And Repository Layers

## Status

Accepted

## Context

The gateway previously concentrated routing, middleware, provider orchestration, admin operations, observability, and persistence in `app/main.py`. That made the service hard to review and risky to extend.

## Decision

The application is split into:

- `bootstrap`: app factory and lifespan wiring
- `config`: typed environment settings
- `runtime`: provider instances and shared mutable runtime state
- `routers`: FastAPI transport layer
- `services`: request orchestration and business logic
- `repositories`: repeated storage access helpers

## Consequences

- Endpoint behavior remains stable while code ownership boundaries are clearer.
- Provider and admin logic can evolve without inflating the app entrypoint.
- Middleware and service behavior can be tested without exercising the whole module graph manually.
