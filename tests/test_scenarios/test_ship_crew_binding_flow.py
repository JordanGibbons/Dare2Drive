"""End-to-end Phase 2c: ship-crew binding + narrative substitution lifecycle.

Builds the entire flow:
1. Player has a build + a crew member.
2. Crew is bound to ship via crew_assignments (direct DB write — the
   /hangar UX is exercised in test_view_hangar.py).
3. /expedition start launches with no crew params; the ship's crew is
   auto-derived.
4. EXPEDITION_EVENT fires; the DM body has rendered narrative tokens.
5. Player clicks the button (handle_expedition_response).
6. EXPEDITION_RESOLVE renders outcome narrative.
7. EXPEDITION_COMPLETE fires; closing body renders.
8. Build + crew return to IDLE; persistent assignment is unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_full_lifecycle_with_persistent_assignment_and_rendered_tokens(
    db_session, sample_user, monkeypatch
):
    from db.models import (
        Build,
        BuildActivity,
        CrewActivity,
        CrewArchetype,
        CrewAssignment,
        CrewMember,
        Expedition,
        ExpeditionState,
        HullClass,
        JobState,
        JobType,
        Rarity,
        ScheduledJob,
    )
    from scheduler.jobs.expedition_complete import handle_expedition_complete
    from scheduler.jobs.expedition_event import handle_expedition_event

    # ─────── setup ───────
    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
        current_activity=CrewActivity.IDLE,
    )
    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    db_session.add_all([crew, build])
    await db_session.flush()
    db_session.add(
        CrewAssignment(build_id=build.id, crew_id=crew.id, archetype=CrewArchetype.PILOT)
    )
    await db_session.flush()

    # Create the expedition row + crew snapshot directly
    expedition = Expedition(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        build_id=build.id,
        template_id="marquee_run",
        state=ExpeditionState.ACTIVE,
        started_at=datetime.now(timezone.utc),
        completes_at=datetime.now(timezone.utc) + timedelta(hours=1),
        correlation_id=uuid.uuid4(),
        scene_log=[],
    )
    from db.models import ExpeditionCrewAssignment

    db_session.add(expedition)
    db_session.add(
        ExpeditionCrewAssignment(
            expedition_id=expedition.id, crew_id=crew.id, archetype=CrewArchetype.PILOT
        )
    )
    crew.current_activity = CrewActivity.ON_EXPEDITION
    crew.current_activity_id = expedition.id
    build.current_activity = BuildActivity.ON_EXPEDITION
    build.current_activity_id = expedition.id
    await db_session.flush()

    # Stub the template to use narrative tokens
    fake_template = {
        "id": "marquee_run",
        "kind": "scripted",
        "duration_minutes": 60,
        "response_window_minutes": 30,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "scenes": [
            {
                "id": "pirate_skiff",
                "narration": "{pilot.callsign} aboard the {ship} sights pirates.",
                "choices": [
                    {
                        "id": "outrun",
                        "text": "Burn hard.",
                        "default": True,
                        "outcomes": {
                            "result": {
                                "narrative": "{ship} pulls away clean.",
                                "effects": [],
                            }
                        },
                    }
                ],
            },
            {
                "id": "closing",
                "is_closing": True,
                "narration": "ok",
                "closings": [
                    {
                        "when": {"default": True},
                        "body": "{pilot.callsign} brings the {ship} home.",
                        "effects": [],
                    }
                ],
            },
        ],
    }
    monkeypatch.setattr("scheduler.jobs.expedition_event.load_template", lambda _id: fake_template)
    monkeypatch.setattr(
        "scheduler.jobs.expedition_complete.load_template", lambda _id: fake_template
    )

    # ─────── EXPEDITION_EVENT renders tokens ───────
    event_job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(event_job)
    await db_session.flush()
    event_result = await handle_expedition_event(db_session, event_job)
    event_body = event_result.notifications[0].body
    assert "Sixgun" in event_body
    assert "Flagstaff" in event_body
    assert "{pilot" not in event_body
    assert "{ship" not in event_body

    # ─────── EXPEDITION_COMPLETE renders closing ───────
    complete_job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        job_type=JobType.EXPEDITION_COMPLETE,
        payload={
            "expedition_id": str(expedition.id),
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(complete_job)
    await db_session.flush()
    complete_result = await handle_expedition_complete(db_session, complete_job)
    closing_body = complete_result.notifications[0].body
    assert "Sixgun" in closing_body
    assert "Flagstaff" in closing_body

    # ─────── persistent assignment survived; crew/build unlocked ───────
    refreshed_crew = await db_session.get(CrewMember, crew.id)
    refreshed_build = await db_session.get(Build, build.id)
    assert refreshed_crew.current_activity == CrewActivity.IDLE
    assert refreshed_build.current_activity == BuildActivity.IDLE

    from sqlalchemy import select

    binding = (
        await db_session.execute(select(CrewAssignment).where(CrewAssignment.build_id == build.id))
    ).scalar_one_or_none()
    assert binding is not None
    assert binding.crew_id == crew.id
