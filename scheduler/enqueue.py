"""Helpers cogs use to atomically enqueue jobs.

Cogs call these inside their own session.begin() block so the Timer + ScheduledJob
inserts (and any cost deductions, crew state updates, etc.) commit together.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    JobState,
    JobType,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
)


async def enqueue_timer(
    session: AsyncSession,
    *,
    user_id: str,
    timer_type: TimerType,
    recipe_id: str,
    completes_at: datetime,
    payload: dict[str, Any] | None = None,
) -> tuple[Timer, ScheduledJob]:
    """Insert a Timer row and a paired ScheduledJob row.

    The ScheduledJob's payload references the timer id; the timer's
    linked_scheduled_job_id back-references the job. Both get UUIDs assigned
    here so we can wire the link before flush.
    """
    timer_id = uuid.uuid4()
    job_id = uuid.uuid4()

    job = ScheduledJob(
        id=job_id,
        user_id=user_id,
        job_type=JobType.TIMER_COMPLETE,
        payload={"timer_id": str(timer_id)},
        scheduled_for=completes_at,
        state=JobState.PENDING,
    )
    timer = Timer(
        id=timer_id,
        user_id=user_id,
        timer_type=timer_type,
        recipe_id=recipe_id,
        payload=payload or {},
        completes_at=completes_at,
        state=TimerState.ACTIVE,
        linked_scheduled_job_id=job_id,
    )
    session.add(job)
    session.add(timer)
    return timer, job


async def enqueue_accrual_tick(
    session: AsyncSession,
    *,
    user_id: str,
    scheduled_for: datetime,
) -> ScheduledJob:
    """Insert a pending accrual_tick ScheduledJob for the given user."""
    job = ScheduledJob(
        user_id=user_id,
        job_type=JobType.ACCRUAL_TICK,
        payload={},
        scheduled_for=scheduled_for,
        state=JobState.PENDING,
    )
    session.add(job)
    return job
