"""End-to-end expedition lifecycle: launch → 2 events → close → unlocks."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_full_expedition_lifecycle(db_session, sample_user):
    """Drive an expedition through every JobType in order, verify final state."""
    from sqlalchemy import select

    from bot.cogs.expeditions import handle_expedition_response
    from db.models import (
        Build,
        BuildActivity,
        CrewActivity,
        CrewArchetype,
        CrewMember,
        Expedition,
        ExpeditionState,
        HullClass,
        JobState,
        JobType,
        Rarity,
        RewardLedger,
        ScheduledJob,
    )
    from scheduler.jobs.expedition_auto_resolve import handle_expedition_auto_resolve
    from scheduler.jobs.expedition_complete import handle_expedition_complete
    from scheduler.jobs.expedition_event import handle_expedition_event
    from scheduler.jobs.expedition_resolve import handle_expedition_resolve

    # --- Set up: user, build, crew (PILOT + GUNNER) ---
    sample_user.currency = 1000
    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    db_session.add(build)
    pilot = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
        stats={"acceleration": 70, "luck": 40, "handling": 50},
        current_activity=CrewActivity.IDLE,
    )
    gunner = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Jax",
        last_name="Krell",
        callsign="Blackjack",
        archetype=CrewArchetype.GUNNER,
        rarity=Rarity.RARE,
        level=3,
        stats={"combat": 65, "luck": 30},
        current_activity=CrewActivity.IDLE,
    )
    db_session.add(pilot)
    db_session.add(gunner)
    await db_session.flush()

    # --- Manually launch the expedition (skipping the cog for test isolation) ---
    from db.models import ExpeditionCrewAssignment

    now = datetime.now(timezone.utc)
    expedition = Expedition(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        build_id=build.id,
        template_id="outer_marker_patrol",
        state=ExpeditionState.ACTIVE,
        started_at=now,
        completes_at=now + timedelta(hours=4),
        correlation_id=uuid.uuid4(),
        scene_log=[],
    )
    db_session.add(expedition)
    await db_session.flush()
    db_session.add(
        ExpeditionCrewAssignment(
            expedition_id=expedition.id,
            crew_id=pilot.id,
            archetype=CrewArchetype.PILOT,
        )
    )
    db_session.add(
        ExpeditionCrewAssignment(
            expedition_id=expedition.id,
            crew_id=gunner.id,
            archetype=CrewArchetype.GUNNER,
        )
    )
    build.current_activity = BuildActivity.ON_EXPEDITION
    build.current_activity_id = expedition.id
    pilot.current_activity = CrewActivity.ON_EXPEDITION
    gunner.current_activity = CrewActivity.ON_EXPEDITION
    pilot.current_activity_id = expedition.id
    gunner.current_activity_id = expedition.id
    await db_session.flush()

    # --- Phase 1: EVENT fires ---
    event_job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "drifting_wreck",
            "template_id": "outer_marker_patrol",
        },
        scheduled_for=now,
        state=JobState.CLAIMED,
    )
    db_session.add(event_job)
    await db_session.flush()
    result = await handle_expedition_event(db_session, event_job)
    await db_session.flush()
    assert len(result.notifications) == 1
    auto_job = (
        await db_session.execute(
            select(ScheduledJob).where(ScheduledJob.job_type == JobType.EXPEDITION_AUTO_RESOLVE)
        )
    ).scalar_one()
    assert auto_job.state == JobState.PENDING

    # --- Phase 2: Player responds via button (handle_expedition_response) ---
    outcome = await handle_expedition_response(
        db_session,
        expedition_id=expedition.id,
        scene_id="drifting_wreck",
        choice_id="leave_it",
        invoking_user_id=expedition.user_id,
    )
    assert outcome["status"] == "accepted"
    await db_session.flush()
    refreshed_auto = await db_session.get(ScheduledJob, auto_job.id)
    assert refreshed_auto.state == JobState.CANCELLED

    # --- Phase 3: RESOLVE fires (auto-enqueued by handle_expedition_response) ---
    resolve = (
        await db_session.execute(
            select(ScheduledJob).where(ScheduledJob.job_type == JobType.EXPEDITION_RESOLVE)
        )
    ).scalar_one()
    resolve.state = JobState.CLAIMED
    await db_session.flush()
    await handle_expedition_resolve(db_session, resolve)
    await db_session.flush()

    refreshed = await db_session.get(Expedition, expedition.id)
    resolved = [e for e in refreshed.scene_log if e.get("status") == "resolved"]
    assert len(resolved) == 1

    # --- Phase 4: Second event fires, NO player response → auto-resolve fires ---
    event2 = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "scope_ghost",
            "template_id": "outer_marker_patrol",
        },
        scheduled_for=now + timedelta(hours=2),
        state=JobState.CLAIMED,
    )
    db_session.add(event2)
    await db_session.flush()
    await handle_expedition_event(db_session, event2)
    await db_session.flush()
    auto2 = (
        await db_session.execute(
            select(ScheduledJob)
            .where(ScheduledJob.job_type == JobType.EXPEDITION_AUTO_RESOLVE)
            .where(ScheduledJob.state == JobState.PENDING)
        )
    ).scalar_one()
    auto2.state = JobState.CLAIMED
    await db_session.flush()
    await handle_expedition_auto_resolve(db_session, auto2)
    await db_session.flush()
    auto_resolve_resolve = (
        await db_session.execute(
            select(ScheduledJob)
            .where(ScheduledJob.job_type == JobType.EXPEDITION_RESOLVE)
            .where(ScheduledJob.state == JobState.PENDING)
        )
    ).scalar_one()
    auto_resolve_resolve.state = JobState.CLAIMED
    await db_session.flush()
    await handle_expedition_resolve(db_session, auto_resolve_resolve)
    await db_session.flush()

    # --- Phase 5: COMPLETE fires ---
    complete = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_COMPLETE,
        payload={"expedition_id": str(expedition.id), "template_id": "outer_marker_patrol"},
        scheduled_for=now + timedelta(hours=4),
        state=JobState.CLAIMED,
    )
    db_session.add(complete)
    await db_session.flush()
    result = await handle_expedition_complete(db_session, complete)
    await db_session.flush()

    # --- Verifications ---
    refreshed = await db_session.get(Expedition, expedition.id)
    assert refreshed.state == ExpeditionState.COMPLETED
    assert refreshed.outcome_summary is not None

    refreshed_build = await db_session.get(Build, build.id)
    assert refreshed_build.current_activity == BuildActivity.IDLE

    refreshed_pilot = await db_session.get(CrewMember, pilot.id)
    refreshed_gunner = await db_session.get(CrewMember, gunner.id)
    assert refreshed_pilot.current_activity == CrewActivity.IDLE
    assert refreshed_gunner.current_activity == CrewActivity.IDLE

    ledger_count = (
        (
            await db_session.execute(
                select(RewardLedger).where(RewardLedger.user_id == expedition.user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(ledger_count) >= 1
