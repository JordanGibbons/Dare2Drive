"""EXPEDITION_COMPLETE handler — closing variant + unlocks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


def _make_complete_job(user_id, expedition_id, template_id="marquee_run"):
    from db.models import JobState, JobType, ScheduledJob

    return ScheduledJob(
        id=uuid.uuid4(),
        user_id=user_id,
        job_type=JobType.EXPEDITION_COMPLETE,
        payload={"expedition_id": str(expedition_id), "template_id": template_id},
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )


@pytest.mark.asyncio
async def test_complete_handler_sets_state_completed(db_session, sample_expedition_with_pilot):
    from db.models import (
        Build,
        BuildActivity,
        CrewActivity,
        CrewMember,
        Expedition,
        ExpeditionState,
    )
    from scheduler.jobs.expedition_complete import handle_expedition_complete

    expedition, pilot = sample_expedition_with_pilot
    expedition.scene_log = [
        {"scene_id": "x", "status": "resolved", "roll": {"success": True}},
    ]
    await db_session.flush()

    job = _make_complete_job(expedition.user_id, expedition.id)
    db_session.add(job)
    await db_session.flush()
    await handle_expedition_complete(db_session, job)
    await db_session.flush()

    refreshed = await db_session.get(Expedition, expedition.id)
    assert refreshed.state == ExpeditionState.COMPLETED
    assert refreshed.outcome_summary is not None

    build = await db_session.get(Build, expedition.build_id)
    assert build.current_activity == BuildActivity.IDLE
    assert build.current_activity_id is None

    crew = await db_session.get(CrewMember, pilot.id)
    assert crew.current_activity == CrewActivity.IDLE
    assert crew.current_activity_id is None


@pytest.mark.asyncio
async def test_complete_handler_preserves_injured_until(db_session, sample_expedition_with_pilot):
    from datetime import timedelta

    from db.models import CrewMember
    from scheduler.jobs.expedition_complete import handle_expedition_complete

    expedition, pilot = sample_expedition_with_pilot
    pilot.injured_until = datetime.now(timezone.utc) + timedelta(hours=24)
    expedition.scene_log = []
    await db_session.flush()

    job = _make_complete_job(expedition.user_id, expedition.id)
    db_session.add(job)
    await db_session.flush()
    await handle_expedition_complete(db_session, job)
    await db_session.flush()

    refreshed = await db_session.get(CrewMember, pilot.id)
    assert refreshed.injured_until is not None  # preserved


@pytest.mark.asyncio
async def test_complete_handler_emits_closing_dm(db_session, sample_expedition_with_pilot):
    from scheduler.jobs.expedition_complete import handle_expedition_complete

    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = []
    await db_session.flush()

    job = _make_complete_job(expedition.user_id, expedition.id)
    db_session.add(job)
    await db_session.flush()
    result = await handle_expedition_complete(db_session, job)
    assert len(result.notifications) == 1
    assert result.notifications[0].category == "expedition_complete"


@pytest.mark.asyncio
async def test_complete_handler_marks_job_completed(db_session, sample_expedition_with_pilot):
    """Regression for the stuck-CLAIMED loop: handler must transition the job to COMPLETED."""
    from db.models import JobState, ScheduledJob
    from scheduler.jobs.expedition_complete import handle_expedition_complete

    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = []
    await db_session.flush()

    job = _make_complete_job(expedition.user_id, expedition.id)
    db_session.add(job)
    await db_session.flush()
    await handle_expedition_complete(db_session, job)
    await db_session.flush()

    refreshed = await db_session.get(ScheduledJob, job.id)
    assert refreshed.state == JobState.COMPLETED


@pytest.mark.asyncio
async def test_complete_handler_body_is_human_readable(db_session, sample_expedition_with_pilot):
    """The closing DM must NOT be a JSON dump."""
    from scheduler.jobs.expedition_complete import handle_expedition_complete

    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = []
    await db_session.flush()

    job = _make_complete_job(expedition.user_id, expedition.id)
    db_session.add(job)
    await db_session.flush()
    result = await handle_expedition_complete(db_session, job)
    body = result.notifications[0].body
    assert not body.lstrip().startswith("{"), f"body looks like JSON: {body[:60]!r}"
    assert "Successes" in body


@pytest.mark.asyncio
async def test_complete_handler_renders_narrative_tokens_in_closing(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    from scheduler.jobs.expedition_complete import handle_expedition_complete

    expedition, pilot = sample_expedition_with_pilot
    expedition.scene_log = []
    await db_session.flush()

    fake_template = {
        "id": "marquee_run",
        "kind": "scripted",
        "duration_minutes": 60,
        "response_window_minutes": 30,
        "cost_credits": 0,
        "crew_required": {"min": 1, "archetypes_any": ["PILOT"]},
        "scenes": [
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
            }
        ],
    }
    monkeypatch.setattr(
        "scheduler.jobs.expedition_complete.load_template", lambda _id: fake_template
    )

    job = _make_complete_job(expedition.user_id, expedition.id)
    db_session.add(job)
    await db_session.flush()

    result = await handle_expedition_complete(db_session, job)
    body = result.notifications[0].body
    assert pilot.callsign in body
    assert "{pilot" not in body
    assert "{ship" not in body
