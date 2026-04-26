"""Tests for scheduler.enqueue — cog-side helper to atomically insert Timer + ScheduledJob."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from db.models import (
    HullClass,
    JobState,
    JobType,
    TimerState,
    TimerType,
    User,
)


@pytest.mark.asyncio
async def test_enqueue_timer_creates_linked_rows(db_session):
    from scheduler.enqueue import enqueue_timer

    user = User(discord_id="800001", username="enq_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    completes_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    timer, job = await enqueue_timer(
        db_session,
        user_id=user.discord_id,
        timer_type=TimerType.TRAINING,
        recipe_id="combat_drills",
        completes_at=completes_at,
        payload={"crew_id": "11111111-1111-1111-1111-111111111111"},
    )
    await db_session.flush()

    assert timer.state == TimerState.ACTIVE
    assert timer.linked_scheduled_job_id == job.id
    assert job.state == JobState.PENDING
    assert job.job_type == JobType.TIMER_COMPLETE
    assert job.scheduled_for == completes_at
    assert job.payload == {"timer_id": str(timer.id)}


@pytest.mark.asyncio
async def test_enqueue_accrual_tick_creates_pending_job(db_session):
    from scheduler.enqueue import enqueue_accrual_tick

    user = User(discord_id="800002", username="enq_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    fires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    job = await enqueue_accrual_tick(db_session, user_id=user.discord_id, scheduled_for=fires_at)
    await db_session.flush()

    assert job.job_type == JobType.ACCRUAL_TICK
    assert job.state == JobState.PENDING
    assert job.scheduled_for == fires_at
    assert job.payload == {}
