#!/bin/sh
set -eu

echo "Running migrations..."
poetry run alembic upgrade head

echo "Starting gateway..."
exec poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000
