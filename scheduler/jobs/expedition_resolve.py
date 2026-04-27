"""EXPEDITION_RESOLVE handler — apply scene outcome + emit DM."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from api.metrics import expedition_event_response_seconds, expedition_events_resolved_total
from config.logging import get_logger
from db.models import Expedition, ExpeditionState, JobState, JobType, ScheduledJob
from engine.expedition_engine import resolve_scene
from engine.expedition_template import load_template
from scheduler.dispatch import HandlerResult, NotificationRequest, register

log = get_logger(__name__)


async def handle_expedition_resolve(session: AsyncSession, job: ScheduledJob) -> HandlerResult:
    expedition_id = uuid.UUID(job.payload["expedition_id"])
    scene_id = job.payload["scene_id"]
    template_id = job.payload["template_id"]
    picked = job.payload.get("picked_choice_id")
    auto_resolved = bool(job.payload.get("auto_resolved", False))

    expedition = await session.get(Expedition, expedition_id, with_for_update=True)
    if expedition is None:
        log.warning("expedition_resolve: expedition %s not found", expedition_id)
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()
    if expedition.state != ExpeditionState.ACTIVE:
        log.info(
            "expedition_resolve: skipping non-active state=%s id=%s",
            expedition.state,
            expedition_id,
        )
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    template = load_template(template_id)
    scene = _find_scene(template, scene_id)
    if scene is None:
        log.error("expedition_resolve: scene %s not found in %s", scene_id, template_id)
        job.state = JobState.COMPLETED
        job.completed_at = func.now()
        return HandlerResult()

    resolution = await resolve_scene(session, expedition, scene, picked)

    # Update scene_log: find the latest pending entry with this scene_id and resolve it.
    scene_log = list(expedition.scene_log or [])
    for entry in reversed(scene_log):
        if entry.get("scene_id") == scene_id and entry.get("status") == "pending":
            entry["status"] = "resolved"
            entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
            entry["choice_id"] = resolution["choice_id"]
            entry["roll"] = resolution["roll"]
            entry["narrative"] = resolution["outcome"].get("narrative")
            entry["auto_resolved"] = resolution["auto_resolved"]
            break
    expedition.scene_log = scene_log
    await session.flush()

    source = "auto" if auto_resolved else "player"
    expedition_events_resolved_total.labels(
        template_id=template_id,
        scene_id=scene_id,
        source=source,
    ).inc()

    fired_at_iso = None
    for e in scene_log:
        if e.get("scene_id") == scene_id and e.get("status") == "resolved":
            fired_at_iso = e.get("fired_at")
            break
    if fired_at_iso:
        fired_at = datetime.fromisoformat(fired_at_iso.replace("Z", "+00:00"))
        delta = (datetime.now(timezone.utc) - fired_at).total_seconds()
        expedition_event_response_seconds.labels(template_id=template_id).observe(delta)

    body = _format_resolution_body(
        narrative=resolution["outcome"].get("narrative", ""),
        auto_resolved=auto_resolved,
    )

    job.state = JobState.COMPLETED
    job.completed_at = func.now()

    return HandlerResult(
        notifications=[
            NotificationRequest(
                user_id=expedition.user_id,
                category="expedition_resolution",
                title=f"Expedition update — {scene_id}",
                body=body,
                correlation_id=str(expedition.correlation_id),
                dedupe_key=f"expedition:{expedition.id}:scene:{scene_id}:resolved",
            )
        ]
    )


def _format_resolution_body(*, narrative: str, auto_resolved: bool) -> str:
    text = narrative.strip()
    if auto_resolved:
        text += "\n\n_(Auto-resolved — no choice was made before the response window expired.)_"
    return text


def _find_scene(template: dict, scene_id: str) -> dict | None:
    if template["kind"] == "scripted":
        for s in template.get("scenes", []):
            if s.get("id") == scene_id:
                return s
        return None
    if template.get("opening", {}).get("id") == scene_id:
        return template["opening"]
    for s in template.get("events", []):
        if s.get("id") == scene_id:
            return s
    return None


register(JobType.EXPEDITION_RESOLVE, handle_expedition_resolve)
