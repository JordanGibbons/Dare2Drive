"""Worker tick loop with SELECT FOR UPDATE SKIP LOCKED."""

from __future__ import annotations

import asyncio
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from config.logging import get_logger
from config.settings import settings
from db.models import JobState, ScheduledJob

log = get_logger(__name__)


async def tick(
    session_maker: async_sessionmaker,
    *,
    batch_size: int | None = None,
) -> Sequence[ScheduledJob]:
    """Claim up to `batch_size` due pending jobs and return them.

    Uses SELECT FOR UPDATE SKIP LOCKED so multiple concurrent tick() calls
    claim disjoint rows. Each claimed row is transitioned pending -> claimed
    in the same transaction; the dispatcher is then called outside the claim tx.

    Caller must construct `session_maker` with `expire_on_commit=False` so the
    returned rows remain readable after the claim transaction commits.
    """
    n = batch_size or settings.SCHEDULER_BATCH_SIZE
    async with session_maker() as session, session.begin():
        rows = (
            (
                await session.execute(
                    select(ScheduledJob)
                    .where(ScheduledJob.state == JobState.PENDING)
                    .where(ScheduledJob.scheduled_for <= func.now())
                    .order_by(ScheduledJob.scheduled_for)
                    .limit(n)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for job in rows:
            job.state = JobState.CLAIMED
            job.claimed_at = func.now()
            job.attempts += 1
        # Flush so DB evaluates func.now(), then refresh to populate Python-side attrs
        # before the session closes and objects become detached.
        await session.flush()
        for job in rows:
            await session.refresh(job)
        # commit on session.begin() exit — claim is durable before any handler runs.
    return rows


async def run_forever(
    session_maker: async_sessionmaker,
    dispatcher,
    *,
    shutdown_event: asyncio.Event,
) -> None:
    """The worker's main loop: tick, dispatch, sleep.

    `dispatcher` is `scheduler.dispatch.dispatch` — passed in to avoid an
    import cycle and to make this loop testable with a fake dispatcher.
    """
    interval = settings.SCHEDULER_TICK_INTERVAL_SECONDS
    batch = settings.SCHEDULER_BATCH_SIZE
    while not shutdown_event.is_set():
        try:
            jobs = await tick(session_maker, batch_size=batch)
        except Exception:
            log.exception("scheduler tick failed")
            jobs = []
        for job in jobs:
            try:
                await dispatcher(job, session_maker)
            except Exception:
                log.exception("scheduler dispatch failed for job_id=%s", job.id)
        if len(jobs) < batch:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
