#!/usr/bin/env bash
set -euo pipefail

echo "==> Running Alembic migrations..."
python -m alembic upgrade head

echo "==> Starting application..."
exec "$@"
