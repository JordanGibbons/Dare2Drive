"""Tests for engine/rewards.py — idempotent ledger writes."""

from __future__ import annotations

import pytest

from db.models import HullClass, RewardSourceType, User


@pytest.mark.asyncio
async def test_apply_reward_credits_user_on_first_call(db_session):
    from engine.rewards import apply_reward

    user = User(discord_id="700001", username="rewards_a", hull_class=HullClass.HAULER, currency=0)
    db_session.add(user)
    await db_session.flush()

    applied = await apply_reward(
        db_session,
        user_id=user.discord_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id="timer:abc-123",
        delta={"credits": 100, "xp": 50},
    )
    await db_session.flush()

    assert applied is True
    refreshed = await db_session.get(User, user.discord_id)
    assert refreshed.currency == 100
    assert refreshed.xp == 50


@pytest.mark.asyncio
async def test_apply_reward_is_idempotent_on_duplicate_source(db_session):
    from engine.rewards import apply_reward

    user = User(discord_id="700002", username="rewards_b", hull_class=HullClass.HAULER, currency=0)
    db_session.add(user)
    await db_session.flush()

    applied1 = await apply_reward(
        db_session,
        user_id=user.discord_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id="timer:dup-1",
        delta={"credits": 100},
    )
    await db_session.flush()
    applied2 = await apply_reward(
        db_session,
        user_id=user.discord_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id="timer:dup-1",
        delta={"credits": 100},
    )
    await db_session.flush()

    assert applied1 is True
    assert applied2 is False  # ON CONFLICT DO NOTHING — second call is a no-op.
    refreshed = await db_session.get(User, user.discord_id)
    assert refreshed.currency == 100  # only credited once.
