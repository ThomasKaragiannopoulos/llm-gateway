# Contributing

## Quality Gates

Every change should pass:

- `poetry run ruff check .`
- `poetry run mypy app tests`
- `poetry run pytest --cov=app --cov-report=term-missing`

## Module Boundaries

- `app/main.py` stays a thin entrypoint.
- `app/bootstrap.py` owns app wiring and lifecycle.
- `app/routers/*` own HTTP concerns only.
- `app/services/*` own orchestration and business rules.
- `app/db/*` own persistence and session concerns.

Do not move data access back into route handlers or `app/main.py`.

## Review Checklist

- Is the runtime/config contract explicit and validated?
- Are error responses consistent?
- Are auth, quota, and tenant boundaries preserved?
- Does the change include tests for happy path and failure path?
- Does the change keep observability useful in production?
