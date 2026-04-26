"""Tests for scheduler.recovery — stuck claims + capped failure retry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from config.settings import settings
from db.models import HullClass, JobState, JobType, ScheduledJob, User


@pytest.mark.asyncio
async def test_recovery_resets_stuck_claimed_to_pending(db_session):
    from scheduler.recovery import recovery_sweep

    user = User(discord_id="920001", username="rec_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    stuck_for = datetime.now(timezone.utc) - timedelta(
        seconds=settings.SCHEDULER_STUCK_CLAIM_TIMEOUT_SECS + 60
    )
    job = ScheduledJob(
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        claimed_at=stuck_for,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    n = await recovery_sweep(sm)
    assert n >= 1

    # Necessary deviation: bulk UPDATE via a separate session does not sync
    # db_session's identity map. Capture the PK before expiring, then force
    # a re-fetch from the DB so the assertion sees the updated state.
    job_id = job.id
    db_session.expire(job)
    refreshed = await db_session.get(ScheduledJob, job_id)
    assert refreshed.state == JobState.PENDING


@pytest.mark.asyncio
async def test_recovery_retries_failed_under_attempt_cap(db_session):
    from scheduler.recovery import recovery_sweep

    user = User(discord_id="920002", username="rec_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    job = ScheduledJob(
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.FAILED,
        last_error="boom",
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    await recovery_sweep(sm)

    job_id = job.id
    db_session.expire(job)
    refreshed = await db_session.get(ScheduledJob, job_id)
    assert refreshed.state == JobState.PENDING


@pytest.mark.asyncio
async def test_recovery_leaves_max_attempts_failures_alone(db_session):
    from scheduler.recovery import recovery_sweep

    user = User(discord_id="920003", username="rec_c", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    job = ScheduledJob(
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.FAILED,
        last_error="boom",
        attempts=settings.SCHEDULER_MAX_ATTEMPTS,
    )
    db_session.add(job)
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    await recovery_sweep(sm)

    job_id = job.id
    db_session.expire(job)
    refreshed = await db_session.get(ScheduledJob, job_id)
    assert refreshed.state == JobState.FAILED  # left as terminal.
