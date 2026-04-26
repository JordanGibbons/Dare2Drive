"""timer_complete handler — dispatches by timer.timer_type."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import (
    CrewActivity,
    CrewMember,
    JobState,
    JobType,
    RewardSourceType,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
)
from engine.crew_xp import award_xp
from engine.rewards import apply_reward
from engine.timer_recipes import get_recipe
from scheduler.dispatch import HandlerResult, NotificationRequest, register

log = get_logger(__name__)


async def handle_timer_complete(session: AsyncSession, job: ScheduledJob) -> HandlerResult:
    timer_id_str = job.payload.get("timer_id")
    if not timer_id_str:
        raise ValueError(f"timer_complete job {job.id} missing timer_id in payload")
    timer = await session.get(Timer, uuid.UUID(timer_id_str), with_for_update=True)
    if timer is None:
        raise ValueError(f"Timer {timer_id_str} not found for job {job.id}")
    if timer.state != TimerState.ACTIVE:
        # Idempotent skip: timer already cancelled or completed in a parallel path.
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    recipe = get_recipe(timer.timer_type, timer.recipe_id)

    if timer.timer_type == TimerType.TRAINING:
        notif = await _resolve_training(session, timer, recipe)
    elif timer.timer_type == TimerType.RESEARCH:
        notif = await _resolve_research(session, timer, recipe)
    elif timer.timer_type == TimerType.SHIP_BUILD:
        notif = await _resolve_ship_build(session, timer, recipe)
    else:
        raise ValueError(f"unhandled timer_type {timer.timer_type}")

    timer.state = TimerState.COMPLETED
    job.state = JobState.COMPLETED
    job.completed_at = func.now()

    return HandlerResult(notifications=[notif])


async def _resolve_training(
    session: AsyncSession, timer: Timer, recipe: dict[str, Any]
) -> NotificationRequest:
    crew_id = uuid.UUID(timer.payload["crew_id"])
    crew = await session.get(CrewMember, crew_id, with_for_update=True)
    if crew is None:
        raise ValueError(f"crew {crew_id} not found for timer {timer.id}")

    xp_amount = int(recipe["rewards"]["xp"])
    applied = await apply_reward(
        session,
        user_id=timer.user_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id=f"timer:{timer.id}",
        delta={"xp": 0, "credits": 0},  # User-scoped fields are zero — XP goes to crew.
    )
    if applied:
        award_xp(crew, xp_amount)

    crew.current_activity = CrewActivity.IDLE
    crew.current_activity_id = None

    return NotificationRequest(
        user_id=timer.user_id,
        category="timer_completion",
        title="Training complete",
        body=f'{crew.first_name} "{crew.callsign}" {crew.last_name} '
        f"gained {xp_amount} XP from {recipe['name']}.",
        correlation_id=str(timer.linked_scheduled_job_id),
        dedupe_key=f"timer:{timer.id}",
    )


async def _resolve_research(
    session: AsyncSession, timer: Timer, recipe: dict[str, Any]
) -> NotificationRequest:
    # v1 research output is a fleet buff; we record it in the ledger but
    # actual buff application lives in stat_resolver in a follow-on task.
    # Here we just close out the timer + notify.
    await apply_reward(
        session,
        user_id=timer.user_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id=f"timer:{timer.id}",
        delta={"fleet_buff": recipe["rewards"]["fleet_buff"]},
    )
    return NotificationRequest(
        user_id=timer.user_id,
        category="timer_completion",
        title="Research complete",
        body=f"{recipe['name']} finished.",
        correlation_id=str(timer.linked_scheduled_job_id),
        dedupe_key=f"timer:{timer.id}",
    )


async def _resolve_ship_build(
    session: AsyncSession, timer: Timer, recipe: dict[str, Any]
) -> NotificationRequest:
    # v1 ship build: ledger entry + notification. Actual hull-creation lives
    # in a separate follow-on (Phase 2a stub — see spec).
    await apply_reward(
        session,
        user_id=timer.user_id,
        source_type=RewardSourceType.TIMER_COMPLETE,
        source_id=f"timer:{timer.id}",
        delta={"new_ship": recipe["rewards"]["new_ship"]},
    )
    return NotificationRequest(
        user_id=timer.user_id,
        category="timer_completion",
        title="Ship build complete",
        body=f"{recipe['name']} delivered to your hangar.",
        correlation_id=str(timer.linked_scheduled_job_id),
        dedupe_key=f"timer:{timer.id}",
    )


# Self-register so the dispatcher picks us up.
register(JobType.TIMER_COMPLETE, handle_timer_complete)
