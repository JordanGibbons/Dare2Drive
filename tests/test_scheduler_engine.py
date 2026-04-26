"""Tests for scheduler.engine — claim semantics under SKIP LOCKED.

Requires a real Postgres (SKIP LOCKED is a PG feature; sqlite cannot exercise it).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.settings import settings
from db.models import HullClass, JobState, JobType, ScheduledJob, User


@pytest.mark.asyncio
async def test_tick_claims_due_pending_jobs(db_session):
    from scheduler.engine import tick

    user = User(discord_id="900001", username="eng_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.add(
        ScheduledJob(
            user_id=user.discord_id,
            job_type=JobType.TIMER_COMPLETE,
            payload={"timer_id": "x"},
            scheduled_for=past,
            state=JobState.PENDING,
        )
    )
    await db_session.flush()

    # tick() requires its own session-maker — we run against the same engine binding.
    bind = db_session.bind
    sm = async_sessionmaker(bind=bind, expire_on_commit=False)

    claimed = await tick(sm, batch_size=10)
    assert len(claimed) == 1
    assert claimed[0].state == JobState.CLAIMED
    assert claimed[0].claimed_at is not None
    assert claimed[0].attempts == 1


@pytest.mark.asyncio
async def test_tick_skips_future_jobs(db_session):
    from scheduler.engine import tick

    user = User(discord_id="900002", username="eng_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.add(
        ScheduledJob(
            user_id=user.discord_id,
            job_type=JobType.TIMER_COMPLETE,
            payload={},
            scheduled_for=future,
            state=JobState.PENDING,
        )
    )
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    claimed = await tick(sm, batch_size=10)
    assert claimed == []


@pytest.mark.asyncio
async def test_concurrent_ticks_each_claim_disjoint_rows():
    """Two simultaneous tick() calls must claim disjoint rows under SKIP LOCKED.

    This test uses the shared docker PG (NOT db_session savepoint) because
    SKIP LOCKED requires real concurrent transactions.
    """
    from scheduler.engine import tick

    eng = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=4)
    sm = async_sessionmaker(bind=eng, expire_on_commit=False)

    async with sm() as s, s.begin():
        user = User(
            discord_id="900100",
            username="eng_concurrent",
            hull_class=HullClass.HAULER,
        )
        s.add(user)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    async with sm() as s, s.begin():
        for _ in range(20):
            s.add(
                ScheduledJob(
                    user_id="900100",
                    job_type=JobType.TIMER_COMPLETE,
                    payload={},
                    scheduled_for=past,
                    state=JobState.PENDING,
                )
            )

    a, b = await asyncio.gather(tick(sm, batch_size=10), tick(sm, batch_size=10))
    a_ids = {j.id for j in a}
    b_ids = {j.id for j in b}
    assert a_ids.isdisjoint(b_ids)
    assert len(a_ids) + len(b_ids) == 20

    # Cleanup so other tests aren't disturbed.
    async with sm() as s, s.begin():
        await s.execute(ScheduledJob.__table__.delete().where(ScheduledJob.user_id == "900100"))
        await s.execute(User.__table__.delete().where(User.discord_id == "900100"))
    await eng.dispose()
