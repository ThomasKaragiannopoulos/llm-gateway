#!/bin/sh
set -e

echo "Waiting for Postgres..."
attempt=0
max_attempts=30
until poetry run python - <<'PY'
import os, sys
import psycopg
from sqlalchemy.engine import make_url

raw_url = os.getenv("DATABASE_URL")
if not raw_url:
    print("DATABASE_URL is not set", file=sys.stderr)
    sys.exit(1)
try:
    url = make_url(raw_url)
    if url.drivername.startswith("postgresql+"):
        url = url.set(drivername="postgresql")
    conninfo = url.render_as_string(hide_password=False)
    with psycopg.connect(conninfo, connect_timeout=2):
        pass
except Exception as exc:
    print(f"Postgres not ready: {exc}", file=sys.stderr)
    sys.exit(1)
PY
do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "Postgres did not become ready in time."
    exit 1
  fi
  sleep 1
done

echo "Running migrations..."
poetry run alembic upgrade head

echo "Starting server..."
exec poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000
