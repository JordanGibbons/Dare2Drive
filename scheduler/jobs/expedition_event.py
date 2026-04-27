"""EXPEDITION_EVENT handler.

Fires when a scheduled scene is due. Loads the scene from the template,
filters visible choices for the player's loadout, builds the DM payload,
enqueues the auto-resolve timeout job, appends a `pending` scene_log entry.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from api.metrics import expedition_events_fired_total
from config.logging import get_logger
from config.settings import settings
from db.models import (
    Expedition,
    ExpeditionState,
    JobState,
    JobType,
    ScheduledJob,
)
from engine.expedition_engine import (
    _assigned_archetypes,
    _filter_visible_choices,
    _ship_hull_class,
)
from engine.expedition_template import load_template
from scheduler.dispatch import HandlerResult, NotificationRequest, register

log = get_logger(__name__)


async def handle_expedition_event(session: AsyncSession, job: ScheduledJob) -> HandlerResult:
    expedition_id = uuid.UUID(job.payload["expedition_id"])
    scene_id = job.payload["scene_id"]
    template_id = job.payload["template_id"]

    expedition = await session.get(Expedition, expedition_id, with_for_update=True)
    if expedition is None:
        log.warning("expedition_event_handler: expedition not found id=%s", expedition_id)
        return HandlerResult()
    if expedition.state != ExpeditionState.ACTIVE:
        log.info(
            "expedition_event_handler: skipping non-active state=%s id=%s",
            expedition.state,
            expedition_id,
        )
        return HandlerResult()

    template = load_template(template_id)
    scene = _find_scene(template, scene_id)
    if scene is None:
        log.error(
            "expedition_event_handler: scene %s not found in template %s", scene_id, template_id
        )
        return HandlerResult()

    # Filter visible choices for this player's loadout.
    archetypes = await _assigned_archetypes(session, expedition.id)
    hull_class = await _ship_hull_class(session, expedition.build_id)
    visible = _filter_visible_choices(scene, archetypes, hull_class)

    # Append `pending` log entry.
    scene_log = list(expedition.scene_log or [])
    scene_log.append(
        {
            "scene_id": scene_id,
            "status": "pending",
            "fired_at": datetime.now(timezone.utc).isoformat(),
            "visible_choice_ids": [c["id"] for c in visible],
        }
    )
    expedition.scene_log = scene_log

    # Enqueue auto-resolve.
    response_window = template.get(
        "response_window_minutes",
        settings.EXPEDITION_RESPONSE_WINDOW_DEFAULT_MIN,
    )
    auto_resolve_at = datetime.now(timezone.utc) + timedelta(minutes=int(response_window))
    auto_job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_AUTO_RESOLVE,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": scene_id,
            "template_id": template_id,
        },
        scheduled_for=auto_resolve_at,
        state=JobState.PENDING,
    )
    session.add(auto_job)
    await session.flush()

    body = json.dumps(
        {
            "type": "expedition_event",
            "expedition_id": str(expedition.id),
            "scene_id": scene_id,
            "narration": scene.get("narration", ""),
            "choices": [{"id": c["id"], "text": c["text"]} for c in visible],
            "auto_resolve_job_id": str(auto_job.id),
            "response_window_minutes": int(response_window),
        }
    )

    expedition_events_fired_total.labels(
        template_id=template_id,
        scene_id=scene_id,
    ).inc()

    return HandlerResult(
        notifications=[
            NotificationRequest(
                user_id=expedition.user_id,
                category="expedition_event",
                title=f"Expedition event — {scene_id}",
                body=body,
                correlation_id=str(expedition.correlation_id),
                dedupe_key=f"expedition:{expedition.id}:scene:{scene_id}",
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


register(JobType.EXPEDITION_EVENT, handle_expedition_event)
