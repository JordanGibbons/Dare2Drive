#!/usr/bin/env bash
set -euo pipefail

if [[ "${SKIP_MIGRATIONS:-false}" != "true" ]]; then
    echo "==> Running Alembic migrations..."
    python -m alembic upgrade head
else
    echo "==> Skipping migrations (SKIP_MIGRATIONS=true)"
fi

echo "==> Starting application..."
exec "$@"
