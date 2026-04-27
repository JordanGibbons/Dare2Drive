"""EXPEDITION_AUTO_RESOLVE — enqueue RESOLVE with no picked choice."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_auto_resolve_enqueues_resolve_job(db_session, sample_expedition_with_pilot):
    from sqlalchemy import select

    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_auto_resolve import handle_expedition_auto_resolve

    expedition, _ = sample_expedition_with_pilot

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_AUTO_RESOLVE,
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

    await handle_expedition_auto_resolve(db_session, job)
    await db_session.flush()

    resolves = (
        (
            await db_session.execute(
                select(ScheduledJob)
                .where(ScheduledJob.job_type == JobType.EXPEDITION_RESOLVE)
                .where(ScheduledJob.user_id == expedition.user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(resolves) == 1
    assert resolves[0].payload["picked_choice_id"] is None
    assert resolves[0].payload["auto_resolved"] is True


@pytest.mark.asyncio
async def test_auto_resolve_marks_job_completed(db_session, sample_expedition_with_pilot):
    """Regression for the stuck-CLAIMED loop: handler must transition the job to COMPLETED."""
    from db.models import JobState, JobType, ScheduledJob
    from scheduler.jobs.expedition_auto_resolve import handle_expedition_auto_resolve

    expedition, _ = sample_expedition_with_pilot
    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_AUTO_RESOLVE,
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

    await handle_expedition_auto_resolve(db_session, job)
    await db_session.flush()

    refreshed = await db_session.get(ScheduledJob, job.id)
    assert refreshed.state == JobState.COMPLETED
