"""Tests for the timer_complete handler — per timer_type sub-handlers."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from db.models import (
    CrewActivity,
    CrewArchetype,
    CrewMember,
    HullClass,
    JobState,
    JobType,
    Rarity,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
    User,
)


@pytest.mark.asyncio
async def test_training_handler_credits_xp_and_frees_crew(db_session):
    from scheduler.jobs.timer_complete import handle_timer_complete

    user = User(discord_id="700101", username="t_a", hull_class=HullClass.HAULER, currency=0)
    db_session.add(user)
    await db_session.flush()

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="Train",
        last_name="Ee",
        callsign="Drill",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
        level=1,
        xp=0,
        current_activity=CrewActivity.TRAINING,
    )
    db_session.add(crew)
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        attempts=1,
    )
    db_session.add(job)
    await db_session.flush()

    timer = Timer(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        timer_type=TimerType.TRAINING,
        recipe_id="combat_drills",
        payload={"crew_id": str(crew.id)},
        completes_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        state=TimerState.ACTIVE,
        linked_scheduled_job_id=job.id,
    )
    db_session.add(timer)
    job.payload = {"timer_id": str(timer.id)}
    await db_session.flush()

    result = await handle_timer_complete(db_session, job)

    refreshed_crew = await db_session.get(CrewMember, crew.id)
    refreshed_timer = await db_session.get(Timer, timer.id)
    refreshed_job = await db_session.get(ScheduledJob, job.id)
    # award_xp(crew, 200) at level=1: 50 XP consumed for level-up (1→2), 150 remaining.
    # Total XP awarded = 200 = xp_consumed_in_levelup(50) + xp_remaining(150).
    assert refreshed_crew.level == 2 and refreshed_crew.xp == 150
    assert refreshed_crew.current_activity == CrewActivity.IDLE
    assert refreshed_crew.current_activity_id is None
    assert refreshed_timer.state == TimerState.COMPLETED
    assert refreshed_job.state == JobState.COMPLETED
    assert len(result.notifications) == 1
    assert result.notifications[0].category == "timer_completion"


@pytest.mark.asyncio
async def test_training_handler_idempotent_on_re_dispatch(db_session):
    """Re-dispatching the same timer_complete job must not double-credit XP."""
    from scheduler.jobs.timer_complete import handle_timer_complete

    user = User(discord_id="700102", username="t_b", hull_class=HullClass.HAULER)
    db_session.add(user)
    await db_session.flush()

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="X",
        last_name="Y",
        callsign="Z",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
        level=1,
        xp=0,
        current_activity=CrewActivity.TRAINING,
    )
    db_session.add(crew)
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
        attempts=2,
    )
    db_session.add(job)
    await db_session.flush()

    timer = Timer(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        timer_type=TimerType.TRAINING,
        recipe_id="combat_drills",
        payload={"crew_id": str(crew.id)},
        completes_at=datetime.now(timezone.utc),
        state=TimerState.ACTIVE,
        linked_scheduled_job_id=job.id,
    )
    db_session.add(timer)
    job.payload = {"timer_id": str(timer.id)}
    await db_session.flush()

    await handle_timer_complete(db_session, job)
    xp_after_first = (await db_session.get(CrewMember, crew.id)).xp

    # Reset state to simulate re-claim and re-fire.
    job.state = JobState.CLAIMED
    timer.state = TimerState.ACTIVE
    await db_session.flush()
    await handle_timer_complete(db_session, job)
    xp_after_second = (await db_session.get(CrewMember, crew.id)).xp

    assert xp_after_first == xp_after_second  # ledger blocked second credit.
