"""Chaos tests — worker kill mid-event recovery + persistent view restart.

The persistent-view restart property is hard to test in-process. It's covered
manually:

  Manual smoke test on dev: launch a real expedition, wait for an event DM,
  restart the bot service via `railway service restart`, click the button on
  the DM. The click must succeed (the persistent view re-binds in setup_hook).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_resolve_job_re_claim_runs_exactly_once(db_session, sample_expedition_with_pilot):
    """Simulate: RESOLVE job is CLAIMED → worker dies → recovery sweep flips back.

    Recovery re-fires as PENDING. Idempotency from the (source_type, source_id)
    constraint means the second fire writes nothing new.
    """
    from sqlalchemy import func, select

    from db.models import JobState, JobType, RewardLedger, ScheduledJob
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

    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_RESOLVE,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": "pirate_skiff",
            "template_id": "marquee_run",
            "picked_choice_id": "comply",
            "auto_resolved": False,
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.CLAIMED,
    )
    db_session.add(job)
    await db_session.flush()

    await handle_expedition_resolve(db_session, job)
    await db_session.flush()

    cnt_after_first = (
        await db_session.execute(
            select(func.count())
            .select_from(RewardLedger)
            .where(RewardLedger.user_id == expedition.user_id)
        )
    ).scalar_one()

    # Now simulate recovery sweep: flip job back to PENDING and re-fire.
    job.state = JobState.PENDING
    await db_session.flush()
    job.state = JobState.CLAIMED
    await db_session.flush()
    await handle_expedition_resolve(db_session, job)
    await db_session.flush()

    cnt_after_second = (
        await db_session.execute(
            select(func.count())
            .select_from(RewardLedger)
            .where(RewardLedger.user_id == expedition.user_id)
        )
    ).scalar_one()
    assert cnt_after_second == cnt_after_first
