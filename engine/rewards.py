"""Idempotent reward application via reward_ledger.

The (source_type, source_id) unique constraint on reward_ledger is the
load-bearing piece — INSERT ... ON CONFLICT DO NOTHING makes handlers
exactly-once-effective without a separate idempotency table.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RewardLedger, RewardSourceType, User


async def apply_reward(
    session: AsyncSession,
    *,
    user_id: str,
    source_type: RewardSourceType,
    source_id: str,
    delta: dict[str, Any],
) -> bool:
    """Apply rewards atomically and idempotently.

    Returns True if rewards were applied (first time seeing this source),
    False if the (source_type, source_id) row already existed (no-op).

    Caller is responsible for the surrounding transaction. The ledger INSERT
    executes immediately as a Core statement (visible inside the transaction
    on return). User-row mutations are ORM-level and flush when the caller
    flushes or commits.
    """
    stmt = (
        pg_insert(RewardLedger)
        .values(
            user_id=user_id,
            source_type=source_type,
            source_id=source_id,
            delta=delta,
        )
        .on_conflict_do_nothing(index_elements=["source_type", "source_id"])
        .returning(RewardLedger.id)
    )
    result = await session.execute(stmt)
    inserted = result.scalar_one_or_none()
    if inserted is None:
        return False  # already applied — caller should treat as success.

    user = await session.get(User, user_id, with_for_update=True)
    if user is None:
        raise ValueError(f"unknown user_id={user_id!r} when applying reward")
    credits = int(delta.get("credits", 0))
    xp = int(delta.get("xp", 0))
    if credits:
        user.currency += credits
    if xp:
        user.xp += xp
    return True
