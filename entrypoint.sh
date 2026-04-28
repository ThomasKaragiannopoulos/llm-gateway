#!/bin/sh
set -eu

case "${DATABASE_URL:-}" in
  sqlite*)
    echo "SQLite detected — skipping Alembic (schema managed by SQLAlchemy create_all)"
    ;;
  *)
    echo "Running migrations..."
    poetry run alembic upgrade head
    ;;
esac

echo "Starting gateway..."
exec poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000
