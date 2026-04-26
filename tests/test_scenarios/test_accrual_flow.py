"""End-to-end accrual flow: assign → tick → /claim → balances applied."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    JobState,
    JobType,
    Rarity,
    ScheduledJob,
    StationAssignment,
    StationType,
    User,
)


@pytest.mark.asyncio
async def test_accrual_tick_then_claim(db_session, monkeypatch):
    from scheduler import dispatch as dispatch_mod
    from scheduler.engine import tick
    from scheduler.enqueue import enqueue_accrual_tick
    from scheduler.jobs import accrual_tick  # noqa — registers handler.

    # 1. Create User (currency=0) and CrewMember (NAVIGATOR, ON_STATION).
    user = User(
        discord_id="800002",
        username="scenario_acc",
        hull_class=HullClass.HAULER,
        currency=0,
    )
    db_session.add(user)
    await db_session.flush()

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="A",
        last_name="C",
        callsign="Crew",
        archetype=CrewArchetype.NAVIGATOR,
        rarity=Rarity.COMMON,
        current_activity=CrewActivity.ON_STATION,
    )
    db_session.add(crew)
    await db_session.flush()

    # 2. Create StationAssignment (CARGO_RUN, last_yield_tick_at=now-30min).
    sa = StationAssignment(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        station_type=StationType.CARGO_RUN,
        crew_id=crew.id,
        last_yield_tick_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    db_session.add(sa)
    await db_session.flush()

    # 3. Set crew.current_activity_id = sa.id.
    crew.current_activity_id = sa.id

    # 4. Enqueue an accrual_tick job with scheduled_for=now-1s.
    job = await enqueue_accrual_tick(
        db_session,
        user_id=user.discord_id,
        scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    await db_session.flush()

    # Capture PKs before any expiry so we don't trigger lazy loads on expired objects.
    user_discord_id = user.discord_id
    sa_id = sa.id
    job_id = job.id

    # 5. Build a sessionmaker bound to the same connection, then tick() + dispatch().
    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    claimed = await tick(sm, batch_size=10)
    assert any(j.id == job_id for j in claimed)
    for j in claimed:
        await dispatch_mod.dispatch(j, sm)

    # 6. Re-read the StationAssignment after dispatch; expire first to bust identity map.
    db_session.expire(sa)
    db_session.expire(job)
    refreshed_sa = await db_session.get(StationAssignment, sa_id)
    assert refreshed_sa.pending_credits > 0

    # 7. Replicate the /claim flow inline — new session via sm, FOR UPDATE locks.
    from db.models import RewardSourceType
    from engine.rewards import apply_reward

    async with sm() as session, session.begin():
        u = await session.get(User, user_discord_id, with_for_update=True)
        sas = await session.get(StationAssignment, sa_id, with_for_update=True)
        total = sas.pending_credits
        await apply_reward(
            session,
            user_id=u.discord_id,
            source_type=RewardSourceType.ACCRUAL_CLAIM,
            source_id=f"accrual_claim:{uuid.uuid4()}",
            delta={"credits": total},
        )
        sas.pending_credits = 0
        sas.pending_xp = 0

    # Capture the pending_credits before expiring so we can compare post-claim.
    credits_claimed = refreshed_sa.pending_credits

    # 8. After the inline /claim commit, expire User and StationAssignment in db_session
    #    to see the post-claim state.
    db_session.expire(user)
    db_session.expire(refreshed_sa)

    final_user = await db_session.get(User, user_discord_id)
    assert final_user.currency >= credits_claimed  # credited.
    final_sa = await db_session.get(StationAssignment, sa_id)
    assert final_sa.pending_credits == 0

    # 9. Self-rescheduling: a fresh accrual_tick is now pending for this user.
    from sqlalchemy import select

    next_tick = (
        await db_session.execute(
            select(ScheduledJob)
            .where(ScheduledJob.user_id == user_discord_id)
            .where(ScheduledJob.job_type == JobType.ACCRUAL_TICK)
            .where(ScheduledJob.state == JobState.PENDING)
        )
    ).scalar_one_or_none()
    assert next_tick is not None
