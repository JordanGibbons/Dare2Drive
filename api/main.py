"""Dare2Drive REST API."""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

import api.metrics  # noqa: F401 — registers all dare2drive_* metrics with the default registry
from api.routes.cards import router as cards_router
from api.routes.races import router as races_router
from api.routes.users import router as users_router
from config.logging import get_logger, setup_logging
from config.tracing import init_tracing

setup_logging()
log = get_logger(__name__)

init_tracing("dare2drive-api")

app = FastAPI(title="Dare2Drive API", version="0.1.0")
FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")

# Expose /metrics for Prometheus scraping (OpenMetrics format to include exemplars).
# Must be called before route registration so the instrumentator sees all routes.
Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/metrics", "/health"],
).instrument(app)


@app.get("/metrics")
async def metrics_endpoint():
    """Serve metrics in OpenMetrics format so Prometheus can scrape exemplars."""
    from prometheus_client import REGISTRY
    from prometheus_client.openmetrics.exposition import generate_latest
    from starlette.responses import Response

    return Response(
        content=generate_latest(REGISTRY),
        media_type="application/openmetrics-text; version=1.0.0; charset=utf-8",
    )


app.include_router(users_router, prefix="/api/users", tags=["users"])
app.include_router(cards_router, prefix="/api/cards", tags=["cards"])
app.include_router(races_router, prefix="/api/races", tags=["races"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
