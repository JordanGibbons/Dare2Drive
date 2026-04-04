"""Card API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Card
from db.session import get_session

router = APIRouter()


class CardResponse(BaseModel):
    id: str
    name: str
    slot: str
    rarity: str
    stats: dict[str, Any]
    art_path: str | None = None
    print_max: int | None = None

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[CardResponse])
async def list_cards(
    slot: str | None = None,
    rarity: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    query = select(Card)
    if slot:
        query = query.where(Card.slot == slot)
    if rarity:
        query = query.where(Card.rarity == rarity)
    query = query.order_by(Card.name)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/{card_id}", response_model=CardResponse)
async def get_card(card_id: str, session: AsyncSession = Depends(get_session)) -> Any:
    import uuid

    try:
        card_uuid = uuid.UUID(card_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid card ID format")
    card = await session.get(Card, card_uuid)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card
