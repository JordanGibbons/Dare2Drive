"""Scenario: end-to-end timer flow — enqueue → tick → dispatch → completion.

Exercises the full scheduler pipeline: enqueue_timer, tick (claim), dispatch
(handler), DB state mutation, and Redis stream notification emission.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

# Import to trigger handler registration.
import scheduler.jobs.timer_complete  # noqa: F401
from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    JobState,
    Rarity,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
    User,
)
from scheduler.dispatch import dispatch
from scheduler.engine import tick
from scheduler.enqueue import enqueue_timer


@pytest.mark.asyncio
async def test_training_timer_full_lifecycle(db_session, redis_client, monkeypatch) -> None:
    """Full lifecycle: enqueue → tick → dispatch → DB state + Redis notification."""

    # 1. Monkeypatch notifications to use the test redis_client and test stream key.
    import scheduler.notifications as notif_mod

    monkeypatch.setattr(notif_mod, "get_redis_client", lambda: redis_client)
    monkeypatch.setattr(notif_mod, "DEFAULT_STREAM_KEY", "d2d:notifications:scenario")

    # 2. Create User and CrewMember.
    user = User(
        discord_id=str(uuid.uuid4().int)[:18],
        username="scenario_pilot",
        hull_class=HullClass.HAULER,
        currency=200,
        xp=0,
    )
    db_session.add(user)
    await db_session.flush()

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="Ava",
        last_name="Scenario",
        callsign="Ace",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
        level=1,
        xp=0,
        current_activity=CrewActivity.IDLE,
    )
    db_session.add(crew)
    await db_session.flush()

    # 3. Enqueue a training timer that fires immediately (completes_at = now - 1s).
    now = datetime.now(timezone.utc)
    async with db_session.begin_nested():
        timer, job = await enqueue_timer(
            db_session,
            user_id=user.discord_id,
            timer_type=TimerType.TRAINING,
            recipe_id="combat_drills",
            completes_at=now - timedelta(seconds=1),
            payload={"crew_id": str(crew.id)},
        )
    # enqueue_timer adds but doesn't flush; flush to persist timer/job rows.
    await db_session.flush()

    # Capture PKs before any expiry so we don't trigger lazy loads on expired objects.
    timer_id = timer.id
    job_id = job.id
    crew_id = crew.id
    user_discord_id = user.discord_id

    # 4. Set crew to TRAINING with current_activity_id pointing at the timer.
    crew.current_activity = CrewActivity.TRAINING
    crew.current_activity_id = timer_id
    await db_session.flush()

    # 5. Build a sessionmaker bound to the same connection as db_session.
    sm = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
    )

    # 6. Tick — claims the due job.
    claimed = await tick(sm, batch_size=10)
    assert len(claimed) == 1, f"Expected 1 claimed job, got {len(claimed)}"

    # 7. Dispatch each claimed job.
    for j in claimed:
        await dispatch(j, sm)

    # 8. Re-read state via db_session.
    # expire() invalidates identity-map cache so the next get() issues a SELECT.
    db_session.expire(timer)
    db_session.expire(job)
    db_session.expire(crew)

    refreshed_timer = await db_session.get(Timer, timer_id)
    refreshed_job = await db_session.get(ScheduledJob, job_id)
    refreshed_crew = await db_session.get(CrewMember, crew_id)

    assert (
        refreshed_timer.state == TimerState.COMPLETED
    ), f"Expected timer COMPLETED, got {refreshed_timer.state}"
    assert (
        refreshed_job.state == JobState.COMPLETED
    ), f"Expected job COMPLETED, got {refreshed_job.state}"
    assert (
        refreshed_crew.current_activity == CrewActivity.IDLE
    ), f"Expected crew IDLE, got {refreshed_crew.current_activity}"
    # award_xp(crew, 200) at level=1: 50 XP consumed for level-up (1→2), 150 remaining.
    assert (
        refreshed_crew.level == 2 and refreshed_crew.xp == 150
    ), f"Expected level=2 xp=150, got level={refreshed_crew.level} xp={refreshed_crew.xp}"

    # 9. Verify Redis stream notification was emitted.
    entries = await redis_client.xrange("d2d:notifications:scenario", count=10)
    assert len(entries) == 1, f"Expected 1 Redis stream entry, got {len(entries)}"
    _entry_id, fields = entries[0]
    assert (
        fields["user_id"] == user_discord_id
    ), f"Expected user_id={user_discord_id!r}, got {fields['user_id']!r}"
    assert (
        fields["category"] == "timer_completion"
    ), f"Expected category='timer_completion', got {fields['category']!r}"
