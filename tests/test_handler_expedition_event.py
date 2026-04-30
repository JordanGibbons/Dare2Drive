"""EXPEDITION_EVENT handler — DM payload + auto-resolve enqueue + scene_log update."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_expedition_event_handler_enqueues_auto_resolve(
    db_session, sample_expedition_with_pilot
):
    from sqlalchemy import select

    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event

    expedition, _ = sample_expedition_with_pilot

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_expedition_event(db_session, job)
    await db_session.flush()

    auto = (
        await db_session.execute(
            select(ScheduledJob)
            .where(ScheduledJob.job_type == JobType.EXPEDITION_AUTO_RESOLVE)
            .where(ScheduledJob.user_id == expedition.user_id)
        )
    ).scalar_one_or_none()
    assert auto is not None
    assert auto.payload["scene_id"] == "pirate_skiff"
    assert auto.payload["expedition_id"] == str(expedition.id)


@pytest.mark.asyncio
async def test_expedition_event_handler_appends_pending_scene_log(
    db_session, sample_expedition_with_pilot
):
    from db.models import Expedition, JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event

    expedition, _ = sample_expedition_with_pilot

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_expedition_event(db_session, job)
    await db_session.flush()

    refreshed = await db_session.get(Expedition, expedition.id)
    pending = [
        e
        for e in (refreshed.scene_log or [])
        if e.get("status") == "pending" and e.get("scene_id") == "pirate_skiff"
    ]
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_expedition_event_handler_returns_notification(
    db_session, sample_expedition_with_pilot
):
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event

    expedition, _ = sample_expedition_with_pilot
    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    result = await handle_expedition_event(db_session, job)
    assert len(result.notifications) == 1
    notif = result.notifications[0]
    assert notif.user_id == expedition.user_id
    assert notif.category == "expedition_event"
    assert "scene_id" in notif.body or "pirate_skiff" in notif.body


@pytest.mark.asyncio
async def test_expedition_event_handler_idempotent_skip_for_completed_expedition(
    db_session, sample_expedition_with_pilot
):
    """If the expedition is already COMPLETED/FAILED, the handler is a no-op."""
    from db.models import ExpeditionState, JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event

    expedition, _ = sample_expedition_with_pilot
    expedition.state = ExpeditionState.COMPLETED
    await db_session.flush()

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    result = await handle_expedition_event(db_session, job)
    assert result.notifications == []
    # The handler MUST mark the job COMPLETED even on the no-op skip path,
    # otherwise recovery_sweep will resurrect it as PENDING and the cycle repeats.
    assert job.state == JobState.COMPLETED


@pytest.mark.asyncio
async def test_expedition_event_handler_marks_job_completed(
    db_session, sample_expedition_with_pilot
):
    """Regression for the stuck-CLAIMED loop: handler must transition the job to COMPLETED."""
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event

    expedition, _ = sample_expedition_with_pilot
    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_expedition_event(db_session, job)
    await db_session.flush()

    refreshed = await db_session.get(ScheduledJob, job.id)
    assert refreshed.state == JobState.COMPLETED


@pytest.mark.asyncio
async def test_expedition_event_handler_body_is_human_readable(
    db_session, sample_expedition_with_pilot
):
    """The DM body must NOT be a JSON dump — it should be readable text."""
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event

    expedition, _ = sample_expedition_with_pilot
    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    result = await handle_expedition_event(db_session, job)
    body = result.notifications[0].body
    # Sanity: not a raw JSON dump
    assert not body.lstrip().startswith("{"), f"body looks like JSON: {body[:60]!r}"
    # Should mention the slash command players use to respond
    assert "/expedition respond" in body
    assert "pirate_skiff" in body


@pytest.mark.asyncio
async def test_event_handler_renders_narrative_tokens_in_body(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    """Narration with {pilot.callsign} and {ship} renders in the DM body."""
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_event import handle_expedition_event

    expedition, pilot = sample_expedition_with_pilot

    # Monkey-patch the template loader so this test owns its scene narration.
    # Patch the name in the handler's module (direct-import binding).
    import scheduler.jobs.expedition_event as event_mod

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
                        "text": "{pilot.callsign} burns hard.",
                        "default": True,
                        "outcomes": {"result": {"narrative": "ok", "effects": []}},
                    },
                ],
            }
        ],
    }
    monkeypatch.setattr(event_mod, "load_template", lambda _id: fake_template)

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_EVENT,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    result = await handle_expedition_event(db_session, job)
    body = result.notifications[0].body

    # The literal `{pilot.callsign}` token must be replaced; the actual pilot's
    # callsign comes from the `sample_expedition_with_pilot` fixture.
    assert pilot.callsign in body
    assert "{pilot" not in body
    assert "{ship" not in body
