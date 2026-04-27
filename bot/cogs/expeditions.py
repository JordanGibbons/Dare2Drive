"""Expeditions cog — persistent button view, response handler, slash commands.

This file is built up across Tasks 17-20:
  - Task 17 (now): persistent view + handle_expedition_response (shared)
  - Task 18: /expedition start
  - Task 19: /expedition status
  - Task 20: /expedition respond
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TypedDict

import discord
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import (
    Expedition,
    ExpeditionState,
    JobState,
    JobType,
    ScheduledJob,
)
from db.session import async_session

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom ID parsing
# ---------------------------------------------------------------------------

CUSTOM_ID_PREFIX = "expedition"


def build_custom_id(expedition_id: uuid.UUID, scene_id: str, choice_id: str) -> str:
    return f"{CUSTOM_ID_PREFIX}:{expedition_id}:{scene_id}:{choice_id}"


def parse_custom_id(custom_id: str) -> tuple[uuid.UUID, str, str] | None:
    parts = custom_id.split(":", 3)
    if len(parts) != 4 or parts[0] != CUSTOM_ID_PREFIX:
        return None
    try:
        eid = uuid.UUID(parts[1])
    except ValueError:
        return None
    return (eid, parts[2], parts[3])


class ResponseOutcome(TypedDict):
    status: str
    detail: str


# ---------------------------------------------------------------------------
# Shared response handler
# ---------------------------------------------------------------------------


async def handle_expedition_response(
    session: AsyncSession,
    *,
    expedition_id: uuid.UUID,
    scene_id: str,
    choice_id: str,
    invoking_user_id: str,
) -> ResponseOutcome:
    """Atomic: cancel auto-resolve PENDING → CANCELLED, enqueue RESOLVE with picked choice.

    Symmetric with Phase 2a's /training cancel. Exactly one of (this method,
    the auto-resolve worker) wins the race via the WHERE state = PENDING guard.
    """
    expedition = await session.get(Expedition, expedition_id, with_for_update=True)
    if expedition is None:
        return {"status": "not_found", "detail": "expedition not found"}
    if expedition.user_id != invoking_user_id:
        return {"status": "not_owner", "detail": "this expedition belongs to another player"}
    if expedition.state != ExpeditionState.ACTIVE:
        return {"status": "not_pending", "detail": f"expedition is {expedition.state.value}"}

    pending_entry = None
    for entry in reversed(expedition.scene_log or []):
        if entry.get("scene_id") == scene_id and entry.get("status") == "pending":
            pending_entry = entry
            break
    if pending_entry is None:
        return {"status": "not_pending", "detail": f"no pending response on scene {scene_id}"}

    visible_ids = pending_entry.get("visible_choice_ids", []) or []
    if choice_id not in visible_ids:
        return {"status": "invalid_choice", "detail": f"choice {choice_id} not available"}

    auto_job_id_str = pending_entry.get("auto_resolve_job_id")
    if not auto_job_id_str:
        return {"status": "not_pending", "detail": "scene_log missing auto_resolve_job_id"}
    auto_job_id = uuid.UUID(auto_job_id_str)

    # Atomic CAS: cancel auto-resolve only if still PENDING.
    result = await session.execute(
        update(ScheduledJob)
        .where(ScheduledJob.id == auto_job_id)
        .where(ScheduledJob.state == JobState.PENDING)
        .values(state=JobState.CANCELLED)
    )
    if (result.rowcount or 0) == 0:
        return {"status": "too_late", "detail": "auto-resolve already fired"}

    # Enqueue an immediate RESOLVE with the picked choice.
    resolve = ScheduledJob(
        id=uuid.uuid4(),
        user_id=expedition.user_id,
        job_type=JobType.EXPEDITION_RESOLVE,
        payload={
            "expedition_id": str(expedition.id),
            "scene_id": scene_id,
            "template_id": pending_entry.get("template_id") or _infer_template_id(expedition),
            "picked_choice_id": choice_id,
            "auto_resolved": False,
        },
        scheduled_for=datetime.now(timezone.utc),
        state=JobState.PENDING,
    )
    session.add(resolve)
    return {"status": "accepted", "detail": f"choice {choice_id} committed"}


def _infer_template_id(expedition: Expedition) -> str:
    return expedition.template_id


# ---------------------------------------------------------------------------
# Persistent button view
# ---------------------------------------------------------------------------


class ExpeditionResponseView(discord.ui.View):
    """A persistent View that handles all expedition button clicks.

    Registered once at bot startup via `bot.add_view(ExpeditionResponseView())`.
    """

    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = (interaction.data or {}).get("custom_id", "") if interaction.data else ""
        parsed = parse_custom_id(custom_id)
        if parsed is None:
            return False
        expedition_id, scene_id, choice_id = parsed

        async with async_session() as session, session.begin():
            outcome = await handle_expedition_response(
                session,
                expedition_id=expedition_id,
                scene_id=scene_id,
                choice_id=choice_id,
                invoking_user_id=str(interaction.user.id),
            )

        msg = _user_facing_message(outcome, choice_id)
        await interaction.response.send_message(msg, ephemeral=True)
        return False


def _user_facing_message(outcome: ResponseOutcome, choice_id: str) -> str:
    s = outcome["status"]
    if s == "accepted":
        return f"Choice committed: **{choice_id}**. Standby for the result."
    if s == "too_late":
        return "Too late — that scene already auto-resolved."
    if s == "not_owner":
        return "This expedition belongs to another player."
    if s == "invalid_choice":
        return "That choice isn't available on your loadout."
    if s == "not_found":
        return "Expedition not found."
    return f"Couldn't process your response: {outcome.get('detail', s)}"


def build_button_components(
    expedition_id: uuid.UUID,
    scene_id: str,
    choices: list[dict[str, str]],
) -> list[discord.ui.Button]:
    """Build a list of Buttons for an event DM."""
    out: list[discord.ui.Button] = []
    for c in choices[:5]:
        btn = discord.ui.Button(
            style=discord.ButtonStyle.primary,
            label=c["text"][:80],
            custom_id=build_custom_id(expedition_id, scene_id, c["id"]),
        )
        out.append(btn)
    return out
