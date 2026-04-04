"""Dare2Drive REST API."""

from __future__ import annotations

from fastapi import FastAPI

from api.routes.cards import router as cards_router
from api.routes.races import router as races_router
from api.routes.users import router as users_router
from config.logging import get_logger, setup_logging

setup_logging()
log = get_logger(__name__)

app = FastAPI(title="Dare2Drive API", version="0.1.0")

app.include_router(users_router, prefix="/api/users", tags=["users"])
app.include_router(cards_router, prefix="/api/cards", tags=["cards"])
app.include_router(races_router, prefix="/api/races", tags=["races"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
