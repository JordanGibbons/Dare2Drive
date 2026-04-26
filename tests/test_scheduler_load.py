"""Load test for scheduler: 1000 concurrent jobs drain under 60 seconds."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.settings import settings
from db.models import HullClass, JobState, JobType, ScheduledJob, User
from scheduler.dispatch import HandlerResult


@pytest.mark.perf
@pytest.mark.asyncio
async def test_thousand_jobs_drain_under_minute(monkeypatch):
    """Load test: 1000 ScheduledJobs claim and complete within 60 seconds.

    Uses a dedicated engine with pool_size=8, max_overflow=4 to avoid
    connection saturation. Replaces the TIMER_COMPLETE handler with a noop
    that marks jobs COMPLETED. Loops tick+dispatch until empty or timeout.
    """
    from scheduler import dispatch as dispatch_mod
    from scheduler.dispatch import dispatch
    from scheduler.engine import tick

    # Create dedicated engine for this test
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_size=8,
        max_overflow=4,
    )
    sm = async_sessionmaker(bind=engine, expire_on_commit=False)

    # Create test user
    async with sm() as s, s.begin():
        user = User(
            discord_id="load_test_user",
            username="load_test",
            hull_class=HullClass.HAULER,
        )
        s.add(user)

    # Install noop handler via monkeypatch (auto-reverts after test)
    async def noop_handler(session, job):
        job.state = JobState.COMPLETED
        return HandlerResult()

    monkeypatch.setitem(dispatch_mod.HANDLERS, JobType.TIMER_COMPLETE, noop_handler)

    # Insert 1000 jobs with scheduled_for=now-1s (all due)
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    batch_size = 100
    for i in range(0, 1000, batch_size):
        async with sm() as s, s.begin():
            for j in range(batch_size):
                s.add(
                    ScheduledJob(
                        user_id="load_test_user",
                        job_type=JobType.TIMER_COMPLETE,
                        payload={"idx": i + j},
                        scheduled_for=past,
                        state=JobState.PENDING,
                    )
                )

    # Drain loop: tick + dispatch until empty or 60s elapse
    start_time = time.time()
    drained = 0
    max_elapsed = 60.0
    batch = settings.SCHEDULER_BATCH_SIZE

    while time.time() - start_time < max_elapsed:
        claimed = await tick(sm, batch_size=batch)
        if not claimed:
            break
        for job in claimed:
            await dispatch(job, sm)
            drained += 1

    elapsed = time.time() - start_time

    # Assertions
    assert drained == 1000, f"Expected 1000 drained, got {drained}"
    assert (
        elapsed < max_elapsed
    ), f"Drained {drained} jobs in {elapsed:.2f}s, exceeds {max_elapsed}s limit"

    # Verify no PENDING rows remain
    async with sm() as s:
        pending_count = 0
        async for row in await s.stream(
            ScheduledJob.__table__.select().where(
                ScheduledJob.user_id == "load_test_user",
                ScheduledJob.state == JobState.PENDING,
            )
        ):
            pending_count += 1
        assert pending_count == 0, f"Found {pending_count} PENDING jobs remaining"

    # Cleanup: delete all 1000 jobs + user
    async with sm() as s, s.begin():
        await s.execute(
            ScheduledJob.__table__.delete().where(ScheduledJob.user_id == "load_test_user")
        )
        await s.execute(User.__table__.delete().where(User.discord_id == "load_test_user"))

    await engine.dispose()
