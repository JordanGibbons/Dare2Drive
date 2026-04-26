"""Tests for scheduler.dispatch — handler registry + per-job transactions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from db.models import HullClass, JobState, JobType, ScheduledJob, User


@pytest.mark.asyncio
async def test_dispatch_runs_handler_and_marks_completed(db_session, monkeypatch):
    from scheduler import dispatch as dispatch_mod
    from scheduler.dispatch import HandlerResult, dispatch

    calls: list[str] = []

    async def fake_timer_complete(session, job):
        calls.append(str(job.id))
        job.state = JobState.COMPLETED
        return HandlerResult()

    monkeypatch.setitem(dispatch_mod.HANDLERS, JobType.TIMER_COMPLETE, fake_timer_complete)

    user = User(discord_id="910001", username="d_a", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    job = ScheduledJob(
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    await dispatch(job, sm)

    assert calls == [str(job.id)]
    refreshed = await db_session.get(ScheduledJob, job.id)
    assert refreshed.state == JobState.COMPLETED


@pytest.mark.asyncio
async def test_dispatch_marks_failed_on_handler_exception(db_session, monkeypatch):
    from scheduler import dispatch as dispatch_mod
    from scheduler.dispatch import dispatch

    async def boom(session, job):
        raise RuntimeError("handler exploded")

    monkeypatch.setitem(dispatch_mod.HANDLERS, JobType.TIMER_COMPLETE, boom)

    user = User(discord_id="910002", username="d_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    job = ScheduledJob(
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    await dispatch(job, sm)

    refreshed = await db_session.get(ScheduledJob, job.id)
    assert refreshed.state == JobState.FAILED
    assert refreshed.last_error and "handler exploded" in refreshed.last_error
