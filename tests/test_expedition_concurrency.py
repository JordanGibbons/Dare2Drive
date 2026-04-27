"""Per-user / per-build expedition concurrency cap."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_max_expeditions_default(db_session, sample_user):
    from engine.expedition_concurrency import get_max_expeditions

    assert await get_max_expeditions(db_session, sample_user) == 2


@pytest.mark.asyncio
async def test_count_active_expeditions_for_user_zero_when_none(db_session, sample_user):
    from engine.expedition_concurrency import count_active_expeditions_for_user

    assert await count_active_expeditions_for_user(db_session, sample_user.discord_id) == 0


@pytest.mark.asyncio
async def test_count_active_expeditions_for_user_increments(
    db_session, sample_expedition_with_pilot
):
    from engine.expedition_concurrency import count_active_expeditions_for_user

    expedition, _ = sample_expedition_with_pilot
    assert await count_active_expeditions_for_user(db_session, expedition.user_id) == 1


@pytest.mark.asyncio
async def test_build_has_active_expedition_true_when_locked(
    db_session, sample_expedition_with_pilot
):
    from engine.expedition_concurrency import build_has_active_expedition

    expedition, _ = sample_expedition_with_pilot
    assert await build_has_active_expedition(db_session, expedition.build_id) is True


@pytest.mark.asyncio
async def test_build_has_active_expedition_false_for_idle_build(db_session, sample_user):
    import uuid

    from db.models import Build, BuildActivity, HullClass
    from engine.expedition_concurrency import build_has_active_expedition

    b = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Spinward",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    db_session.add(b)
    await db_session.flush()
    assert await build_has_active_expedition(db_session, b.id) is False
