"""Chaos test: stuck-claim recovery + handler idempotency end-to-end."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from config.settings import settings
from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    JobState,
    JobType,
    Rarity,
    RewardLedger,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
    User,
)


@pytest.mark.asyncio
async def test_stuck_claim_recovered_and_handler_idempotent(db_session, monkeypatch):
    """End-to-end chaos scenario:

    1. Create a stuck CLAIMED job.
    2. recovery_sweep() resets it to PENDING.
    3. tick() claims it; dispatch() runs the handler once.
    4. A second dispatch() call (redelivery) is a no-op (CLAIMED guard).
    5. XP credited exactly once; exactly one RewardLedger row.
    """
    import scheduler.jobs.timer_complete  # noqa: F401 — triggers handler self-registration
    from scheduler import dispatch as dispatch_mod
    from scheduler.engine import tick
    from scheduler.recovery import recovery_sweep

    # ── 1. Setup: user + crew ──────────────────────────────────────────────

    user = User(
        discord_id="960001",
        username="chaos_a",
        hull_class=HullClass.HAULER,
        currency=0,
    )
    db_session.add(user)
    await db_session.flush()

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="Chaos",
        last_name="Pilot",
        callsign="Wreck",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
        level=1,
        xp=0,
        current_activity=CrewActivity.TRAINING,
    )
    db_session.add(crew)
    await db_session.flush()

    # ── 2. Stuck CLAIMED job (claimed_at well past timeout) ────────────────

    stuck_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.SCHEDULER_STUCK_CLAIM_TIMEOUT_SECS + 120
    )
    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=5),
        state=JobState.CLAIMED,
        claimed_at=stuck_at,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    # ── 3. Timer linked to the stuck job ──────────────────────────────────

    timer = Timer(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        timer_type=TimerType.TRAINING,
        recipe_id="combat_drills",
        payload={"crew_id": str(crew.id)},
        completes_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        state=TimerState.ACTIVE,
        linked_scheduled_job_id=job.id,
    )
    db_session.add(timer)
    job.payload = {"timer_id": str(timer.id)}
    await db_session.flush()

    # ── 4. recovery_sweep() resets the stuck claim ────────────────────────

    sm = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    n = await recovery_sweep(sm)
    assert n >= 1

    # Identity-map staleness: expire then re-fetch.
    job_id = job.id
    db_session.expire(job)
    refreshed_job = await db_session.get(ScheduledJob, job_id)
    assert refreshed_job.state == JobState.PENDING

    # ── 5. tick() claims the job ──────────────────────────────────────────

    claimed = await tick(sm, batch_size=10)
    # The job we care about must be in the claimed batch.
    claimed_ids = {j.id for j in claimed}
    assert job_id in claimed_ids

    # ── 6. dispatch() runs the handler ────────────────────────────────────

    # Locate the freshly-claimed job object returned by tick().
    claimed_job = next(j for j in claimed if j.id == job_id)
    await dispatch_mod.dispatch(claimed_job, sm)

    # ── 7. Second dispatch() with the original job object (redelivery) ────
    #
    # After the first dispatch the row is COMPLETED.  The guard in dispatch()
    # re-fetches the row; seeing state != CLAIMED it silently returns without
    # calling the handler again.

    await dispatch_mod.dispatch(job, sm)

    # ── 8. Assertions ─────────────────────────────────────────────────────

    # Expire crew before re-reading to bypass identity-map cache.
    crew_id = crew.id
    db_session.expire(crew)
    refreshed_crew = await db_session.get(CrewMember, crew_id)

    # award_xp(crew, 200) from level=1, xp=0:
    #   xp += 200 → 200; xp_for_next(1) = 50 → level-up; xp -= 50 → 150, level = 2
    #   xp_for_next(2) = 200 > 150 → stop.  Final: level=2, xp=150.
    assert refreshed_crew.level == 2 and refreshed_crew.xp == 150  # exactly once.

    # Exactly one RewardLedger row for this timer.
    rows = (
        (
            await db_session.execute(
                select(RewardLedger).where(RewardLedger.source_id == f"timer:{timer.id}")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
