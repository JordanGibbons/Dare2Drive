"""EXPEDITION_RESOLVE handler — apply scene outcome + emit DM."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import Expedition, ExpeditionState, JobType, ScheduledJob
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
        return HandlerResult()
    if expedition.state != ExpeditionState.ACTIVE:
        log.info(
            "expedition_resolve: skipping non-active state=%s id=%s",
            expedition.state,
            expedition_id,
        )
        return HandlerResult()

    template = load_template(template_id)
    scene = _find_scene(template, scene_id)
    if scene is None:
        log.error("expedition_resolve: scene %s not found in %s", scene_id, template_id)
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

    body = json.dumps(
        {
            "type": "expedition_resolution",
            "expedition_id": str(expedition.id),
            "scene_id": scene_id,
            "narrative": resolution["outcome"].get("narrative", ""),
            "auto_resolved": auto_resolved,
            "roll": resolution["roll"],
        }
    )
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
