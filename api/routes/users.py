"""User API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, WreckLog
from db.session import get_session

router = APIRouter()


class UserResponse(BaseModel):
    discord_id: str
    username: str
    body_type: str
    currency: int
    xp: int

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    discord_id: str
    username: str
    body_type: str


@router.get("/", response_model=list[UserResponse])
async def list_users(session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(select(User).order_by(User.xp.desc()).limit(100))
    return result.scalars().all()


@router.get("/{discord_id}", response_model=UserResponse)
async def get_user(discord_id: str, session: AsyncSession = Depends(get_session)) -> Any:
    user = await session.get(User, discord_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{discord_id}/wrecks")
async def get_user_wrecks(discord_id: str, session: AsyncSession = Depends(get_session)) -> Any:
    result = await session.execute(
        select(WreckLog)
        .where(WreckLog.user_id == discord_id)
        .order_by(WreckLog.created_at.desc())
        .limit(50)
    )
    logs = result.scalars().all()
    return [
        {
            "id": str(wl.id),
            "race_id": str(wl.race_id),
            "lost_parts": wl.lost_parts,
            "created_at": wl.created_at.isoformat() if wl.created_at else None,
        }
        for wl in logs
    ]
