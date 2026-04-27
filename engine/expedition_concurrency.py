"""Per-user / per-build expedition concurrency caps."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models import Expedition, ExpeditionState, User


async def get_max_expeditions(session: AsyncSession, user: User) -> int:
    """Return how many concurrent active expeditions this user is allowed.

    v1: returns the global default. Future: scale by user level, premium tier,
    or whatever raise mechanic we add. Always called via this function so the
    raise-path is a single-file change.
    """
    return settings.EXPEDITION_MAX_PER_USER_DEFAULT


async def count_active_expeditions_for_user(session: AsyncSession, user_id: str) -> int:
    """Count ACTIVE expeditions for a user."""
    result = await session.execute(
        select(func.count())
        .select_from(Expedition)
        .where(Expedition.user_id == user_id)
        .where(Expedition.state == ExpeditionState.ACTIVE)
    )
    return int(result.scalar_one() or 0)


async def build_has_active_expedition(session: AsyncSession, build_id: uuid.UUID) -> bool:
    """True iff there's an ACTIVE expedition on this build."""
    result = await session.execute(
        select(Expedition.id)
        .where(Expedition.build_id == build_id)
        .where(Expedition.state == ExpeditionState.ACTIVE)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None
