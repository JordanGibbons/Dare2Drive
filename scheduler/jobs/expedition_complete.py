"""EXPEDITION_COMPLETE handler — closing variant + unlocks."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.metrics import expedition_active, expeditions_completed_total
from config.logging import get_logger
from db.models import (
    Build,
    BuildActivity,
    CrewActivity,
    CrewMember,
    Expedition,
    ExpeditionCrewAssignment,
    ExpeditionState,
    JobState,
    JobType,
    ScheduledJob,
)
from engine.effect_registry import apply_effect
from engine.expedition_engine import accumulated_state, select_closing
from engine.expedition_template import load_template
from engine.narrative_render import render
from scheduler.dispatch import HandlerResult, NotificationRequest, register
from scheduler.jobs._render_context import build_render_context

log = get_logger(__name__)


async def handle_expedition_complete(session: AsyncSession, job: ScheduledJob) -> HandlerResult:
    expedition_id = uuid.UUID(job.payload["expedition_id"])
    template_id = job.payload["template_id"]

    expedition = await session.get(Expedition, expedition_id, with_for_update=True)
    if expedition is None:
        log.warning("expedition_complete: %s not found", expedition_id)
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()
    if expedition.state != ExpeditionState.ACTIVE:
        log.info("expedition_complete: already %s", expedition.state)
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    template = load_template(template_id)
    closings = _all_closings(template)
    state = accumulated_state(expedition)
    closing = select_closing(closings, state)

    # Apply closing effects (idempotent via apply_reward source_id).
    for eff in closing.get("effects", []) or []:
        await apply_effect(session, expedition, scene_id="closing", effect=eff)

    # Build outcome summary.
    expedition.state = ExpeditionState.COMPLETED
    expedition.outcome_summary = {
        "closing_body": closing.get("body", ""),
        "successes": state["successes"],
        "failures": state["failures"],
        "flags": sorted(state["flags"]),
    }

    # Unlock build.
    build = await session.get(Build, expedition.build_id, with_for_update=True)
    if build is not None:
        build.current_activity = BuildActivity.IDLE
        build.current_activity_id = None

    # Unlock crew (preserve `injured_until`).
    assignments = (
        (
            await session.execute(
                select(ExpeditionCrewAssignment.crew_id).where(
                    ExpeditionCrewAssignment.expedition_id == expedition.id
                )
            )
        )
        .scalars()
        .all()
    )
    if assignments:
        await session.execute(
            update(CrewMember)
            .where(CrewMember.id.in_(assignments))
            .values(current_activity=CrewActivity.IDLE, current_activity_id=None)
        )

    if state["failures"] == 0:
        outcome_label = "success"
    elif state["successes"] == 0:
        outcome_label = "failure"
    else:
        outcome_label = "partial"
    expeditions_completed_total.labels(
        template_id=template_id,
        outcome=outcome_label,
    ).inc()
    expedition_active.dec()

    ctx = await build_render_context(session, expedition)
    rendered_closing = render(closing.get("body", ""), ctx)
    body = _format_complete_body(
        narrative=rendered_closing,
        summary=expedition.outcome_summary,
    )

    job.state = JobState.COMPLETED
    job.completed_at = func.now()

    return HandlerResult(
        notifications=[
            NotificationRequest(
                user_id=expedition.user_id,
                category="expedition_complete",
                title="Expedition complete",
                body=body,
                correlation_id=str(expedition.correlation_id),
                dedupe_key=f"expedition:{expedition.id}:complete",
            )
        ]
    )


def _format_complete_body(*, narrative: str, summary: dict) -> str:
    successes = int(summary.get("successes", 0))
    failures = int(summary.get("failures", 0))
    flags = list(summary.get("flags", []) or [])
    lines = [narrative.strip(), ""]
    lines.append(f"Successes: **{successes}** · Failures: **{failures}**")
    if flags:
        lines.append("Flags: " + ", ".join(f"`{f}`" for f in flags))
    return "\n".join(lines)


def _all_closings(template: dict) -> list[dict]:
    if template["kind"] == "scripted":
        out: list[dict] = []
        for scene in template.get("scenes", []):
            if scene.get("is_closing"):
                out.extend(scene.get("closings", []))
        return out
    return list(template.get("closings", []))


register(JobType.EXPEDITION_COMPLETE, handle_expedition_complete)
