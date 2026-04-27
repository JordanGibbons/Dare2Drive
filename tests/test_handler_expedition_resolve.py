"""EXPEDITION_RESOLVE — invoke resolve_scene + update scene_log + emit DM."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


def _make_resolve_job(user_id, expedition_id, scene_id, picked, template_id="marquee_run"):
    from db.models import JobState, JobType, ScheduledJob

    return ScheduledJob(
        id=uuid.uuid4(),
        user_id=user_id,
        job_type=JobType.EXPEDITION_RESOLVE,
        payload={
            "expedition_id": str(expedition_id),
            "scene_id": scene_id,
            "template_id": template_id,
            "picked_choice_id": picked,
            "auto_resolved": picked is None,
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )


@pytest.mark.asyncio
async def test_resolve_handler_updates_scene_log_to_resolved(
    db_session, sample_expedition_with_pilot
):
    from db.models import Expedition
    from scheduler.jobs.expedition_resolve import handle_expedition_resolve

    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = [
        {
            "scene_id": "pirate_skiff",
            "status": "pending",
            "fired_at": "2026-04-26T12:00:00Z",
            "visible_choice_ids": ["outrun", "comply"],
        },
    ]
    await db_session.flush()

    job = _make_resolve_job(expedition.user_id, expedition.id, "pirate_skiff", "comply")
    db_session.add(job)
    await db_session.flush()
    await handle_expedition_resolve(db_session, job)
    await db_session.flush()

    refreshed = await db_session.get(Expedition, expedition.id)
    assert refreshed.scene_log[0]["status"] == "resolved"
    assert refreshed.scene_log[0]["choice_id"] == "comply"


@pytest.mark.asyncio
async def test_resolve_handler_returns_notification(db_session, sample_expedition_with_pilot):
    from scheduler.jobs.expedition_resolve import handle_expedition_resolve

    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = [
        {
            "scene_id": "pirate_skiff",
            "status": "pending",
            "fired_at": "2026-04-26T12:00:00Z",
            "visible_choice_ids": ["outrun", "comply"],
        },
    ]
    await db_session.flush()

    job = _make_resolve_job(expedition.user_id, expedition.id, "pirate_skiff", "comply")
    db_session.add(job)
    await db_session.flush()
    result = await handle_expedition_resolve(db_session, job)
    assert len(result.notifications) == 1
    assert result.notifications[0].category == "expedition_resolution"


@pytest.mark.asyncio
async def test_resolve_handler_idempotent_on_re_fire(db_session, sample_expedition_with_pilot):
    """Re-running RESOLVE for the same scene must not double-write rewards."""
    from sqlalchemy import func, select

    from db.models import RewardLedger
    from scheduler.jobs.expedition_resolve import handle_expedition_resolve

    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = [
        {
            "scene_id": "pirate_skiff",
            "status": "pending",
            "fired_at": "2026-04-26T12:00:00Z",
            "visible_choice_ids": ["outrun", "comply"],
        },
    ]
    await db_session.flush()

    for _ in range(2):
        job = _make_resolve_job(expedition.user_id, expedition.id, "pirate_skiff", "comply")
        db_session.add(job)
        await db_session.flush()
        await handle_expedition_resolve(db_session, job)
        await db_session.flush()

    cnt = (
        await db_session.execute(
            select(func.count())
            .select_from(RewardLedger)
            .where(RewardLedger.user_id == expedition.user_id)
        )
    ).scalar_one()
    assert cnt == 1
