"""EXPEDITION_AUTO_RESOLVE handler — fires when the response window elapses.

Enqueues an EXPEDITION_RESOLVE job with `picked_choice_id=None` so the
resolver uses the scene's default choice.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import JobState, JobType, ScheduledJob
from scheduler.dispatch import HandlerResult, register

log = get_logger(__name__)


async def handle_expedition_auto_resolve(session: AsyncSession, job: ScheduledJob) -> HandlerResult:
    resolve = ScheduledJob(
        id=uuid.uuid4(),
        user_id=job.user_id,
        job_type=JobType.EXPEDITION_RESOLVE,
        payload={
            "expedition_id": job.payload["expedition_id"],
            "scene_id": job.payload["scene_id"],
            "template_id": job.payload["template_id"],
            "picked_choice_id": None,
            "auto_resolved": True,
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.PENDING,
    )
    session.add(resolve)
    await session.flush()
    return HandlerResult()


register(JobType.EXPEDITION_AUTO_RESOLVE, handle_expedition_auto_resolve)
