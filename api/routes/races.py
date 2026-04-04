"""Race API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Race
from db.session import get_session

router = APIRouter()


@router.get("/")
async def list_races(
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> Any:
    query = select(Race).order_by(Race.created_at.desc()).limit(min(limit, 100))
    result = await session.execute(query)
    races = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "participants": r.participants,
            "environment": r.environment,
            "results": r.results,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in races
    ]


@router.get("/{race_id}")
async def get_race(race_id: str, session: AsyncSession = Depends(get_session)) -> Any:
    import uuid

    try:
        race_uuid = uuid.UUID(race_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid race ID format")
    race = await session.get(Race, race_uuid)
    if not race:
        raise HTTPException(status_code=404, detail="Race not found")
    return {
        "id": str(race.id),
        "participants": race.participants,
        "environment": race.environment,
        "results": race.results,
        "created_at": race.created_at.isoformat() if race.created_at else None,
    }
