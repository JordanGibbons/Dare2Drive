"""Tests for accrual_tick handler — pending yield accumulation + self-reschedule."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

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
async def test_accrual_tick_accumulates_pending_yield(db_session):
    from scheduler.jobs.accrual_tick import handle_accrual_tick

    user = User(discord_id="710001", username="acc_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="N",
        last_name="V",
        callsign="Nav",
        archetype=CrewArchetype.NAVIGATOR,
        rarity=Rarity.COMMON,
        current_activity=CrewActivity.ON_STATION,
    )
    db_session.add(crew)
    await db_session.flush()

    sa = StationAssignment(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        station_type=StationType.CARGO_RUN,
        crew_id=crew.id,
        last_yield_tick_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    db_session.add(sa)
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        job_type=JobType.ACCRUAL_TICK,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_accrual_tick(db_session, job)

    refreshed = await db_session.get(StationAssignment, sa.id)
    assert refreshed.pending_credits > 0
    assert refreshed.pending_xp > 0


@pytest.mark.asyncio
async def test_accrual_tick_self_reschedules_next_tick(db_session):
    from scheduler.jobs.accrual_tick import handle_accrual_tick

    user = User(discord_id="710002", username="acc_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="X",
        last_name="Y",
        callsign="Z",
        archetype=CrewArchetype.GUNNER,
        rarity=Rarity.COMMON,
        current_activity=CrewActivity.ON_STATION,
    )
    db_session.add(crew)
    await db_session.flush()

    sa = StationAssignment(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        station_type=StationType.WATCH_TOWER,
        crew_id=crew.id,
    )
    db_session.add(sa)
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        job_type=JobType.ACCRUAL_TICK,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_accrual_tick(db_session, job)
    await db_session.flush()

    next_tick = (
        await db_session.execute(
            select(ScheduledJob)
            .where(ScheduledJob.user_id == user.discord_id)
            .where(ScheduledJob.job_type == JobType.ACCRUAL_TICK)
            .where(ScheduledJob.state == JobState.PENDING)
        )
    ).scalar_one_or_none()
    assert next_tick is not None


@pytest.mark.asyncio
async def test_accrual_tick_no_assignments_does_not_reschedule(db_session):
    """If user has zero active assignments, the cycle stops."""
    from scheduler.jobs.accrual_tick import handle_accrual_tick

    user = User(discord_id="710003", username="acc_c", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        job_type=JobType.ACCRUAL_TICK,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_accrual_tick(db_session, job)
    await db_session.flush()

    pending = (
        await db_session.execute(
            select(ScheduledJob)
            .where(ScheduledJob.user_id == user.discord_id)
            .where(ScheduledJob.job_type == JobType.ACCRUAL_TICK)
            .where(ScheduledJob.state == JobState.PENDING)
        )
    ).all()
    assert pending == []
