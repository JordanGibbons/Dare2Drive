#!/usr/bin/env bash
set -euo pipefail

if [[ "${SKIP_MIGRATIONS:-false}" != "true" ]]; then
    echo "==> Running Alembic migrations..."
    python -m alembic upgrade head

    echo "==> Seeding card data..."
    python scripts/seed_cards.py
else
    echo "==> Skipping migrations and seed (SKIP_MIGRATIONS=true)"
fi

echo "==> Starting application..."
exec "$@"
