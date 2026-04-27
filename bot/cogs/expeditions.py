"""Expeditions cog — persistent button view, response handler, slash commands.

This file is built up across Tasks 17-20:
  - Task 17 (now): persistent view + handle_expedition_response (shared)
  - Task 18: /expedition start
  - Task 19: /expedition status
  - Task 20: /expedition respond
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from random import Random
from typing import TypedDict

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.system_gating import get_active_system, system_required_message
from config.logging import get_logger
from config.settings import settings
from db.models import (
    Build,
    BuildActivity,
    CrewActivity,
    CrewArchetype,
    CrewMember,
    Expedition,
    ExpeditionCrewAssignment,
    ExpeditionState,
    JobState,
    JobType,
    ScheduledJob,
    User,
)
from db.session import async_session
from engine.expedition_concurrency import (
    build_has_active_expedition,
    count_active_expeditions_for_user,
    get_max_expeditions,
)
from engine.expedition_template import (
    TemplateValidationError,
    load_template,
)

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


# ---------------------------------------------------------------------------
# Cog with /expedition slash commands.
# ---------------------------------------------------------------------------


class ExpeditionsCog(commands.Cog):
    """Phase 2b — /expedition start, status, respond."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    expedition = app_commands.Group(name="expedition", description="Multi-hour expeditions")

    @expedition.command(name="start", description="Launch a new expedition.")
    @app_commands.describe(
        template="Expedition template id",
        build="Which build (ship) to deploy",
        pilot="Optional: assigned PILOT (display name)",
        gunner="Optional: assigned GUNNER",
        engineer="Optional: assigned ENGINEER",
        navigator="Optional: assigned NAVIGATOR",
    )
    async def expedition_start(
        self,
        interaction: discord.Interaction,
        template: str,
        build: str,
        pilot: str | None = None,
        gunner: str | None = None,
        engineer: str | None = None,
        navigator: str | None = None,
    ) -> None:
        # 1. Template exists?
        try:
            tmpl = load_template(template)
        except (TemplateValidationError, FileNotFoundError):
            await interaction.response.send_message(
                f"Unknown template: `{template}`.", ephemeral=True
            )
            return

        async with async_session() as session, session.begin():
            sys = await get_active_system(interaction, session)
            if sys is None:
                await interaction.response.send_message(
                    system_required_message(),
                    ephemeral=True,
                )
                return

            user = await session.get(User, str(interaction.user.id), with_for_update=True)
            if user is None:
                await interaction.response.send_message(
                    "You don't have a profile yet — run `/start` first.",
                    ephemeral=True,
                )
                return

            # 2. Concurrency cap
            max_active = await get_max_expeditions(session, user)
            current = await count_active_expeditions_for_user(session, user.discord_id)
            if current >= max_active:
                await interaction.response.send_message(
                    f"You're at the max active expedition limit ({current}/{max_active}). "
                    "Wait for one to complete.",
                    ephemeral=True,
                )
                return

            # 3. Cost
            cost = int(tmpl.get("cost_credits", 0))
            if user.currency < cost:
                await interaction.response.send_message(
                    f"You need {cost} credits — you have {user.currency}.",
                    ephemeral=True,
                )
                return

            # 4. Build owned, IDLE
            try:
                build_uuid = uuid.UUID(build)
            except ValueError:
                await interaction.response.send_message(
                    "Pick a valid build from the autocomplete list.",
                    ephemeral=True,
                )
                return
            build_row = await session.get(Build, build_uuid, with_for_update=True)
            if build_row is None or build_row.user_id != user.discord_id:
                await interaction.response.send_message(
                    "Build not found in your fleet.",
                    ephemeral=True,
                )
                return
            if build_row.current_activity != BuildActivity.IDLE:
                await interaction.response.send_message(
                    f"Build `{build_row.name}` is already on expedition.",
                    ephemeral=True,
                )
                return
            if await build_has_active_expedition(session, build_row.id):
                await interaction.response.send_message(
                    f"Build `{build_row.name}` already has an active expedition.",
                    ephemeral=True,
                )
                return

            # 5. Resolve crew picks
            crew_picks: list[tuple[CrewArchetype, CrewMember]] = []
            for arche, display in (
                (CrewArchetype.PILOT, pilot),
                (CrewArchetype.GUNNER, gunner),
                (CrewArchetype.ENGINEER, engineer),
                (CrewArchetype.NAVIGATOR, navigator),
            ):
                if display is None:
                    continue
                row = await _lookup_crew_by_display(session, user.discord_id, display)
                if row is None:
                    await interaction.response.send_message(
                        f"Crew member `{display}` not found.",
                        ephemeral=True,
                    )
                    return
                if row.archetype != arche:
                    await interaction.response.send_message(
                        f"`{display}` is a {row.archetype.value}, " f"not a {arche.value}.",
                        ephemeral=True,
                    )
                    return
                if row.current_activity != CrewActivity.IDLE:
                    await interaction.response.send_message(
                        f"`{display}` is currently {row.current_activity.value}.",
                        ephemeral=True,
                    )
                    return
                if row.injured_until and row.injured_until > datetime.now(timezone.utc):
                    await interaction.response.send_message(
                        f"`{display}` is recovering — back later.",
                        ephemeral=True,
                    )
                    return
                crew_picks.append((arche, row))

            # 6. crew_required minimums
            req = tmpl.get("crew_required", {}) or {}
            if len(crew_picks) < req.get("min", 0):
                await interaction.response.send_message(
                    f"Template `{template}` requires at least {req['min']} crew. "
                    f"You assigned {len(crew_picks)}.",
                    ephemeral=True,
                )
                return
            picked_archetypes = {a.value for a, _ in crew_picks}
            picked_archetypes_upper = {a.upper() for a in picked_archetypes}
            if "archetypes_any" in req:
                if not (set(req["archetypes_any"]) & picked_archetypes_upper):
                    await interaction.response.send_message(
                        f"Template `{template}` requires at least one of "
                        f"{req['archetypes_any']}. You assigned {sorted(picked_archetypes_upper)}.",
                        ephemeral=True,
                    )
                    return
            if "archetypes_all" in req:
                missing = set(req["archetypes_all"]) - picked_archetypes_upper
                if missing:
                    await interaction.response.send_message(
                        f"Template `{template}` requires all of "
                        f"{req['archetypes_all']}. Missing: {sorted(missing)}.",
                        ephemeral=True,
                    )
                    return

            # 7. Atomic creation
            now = datetime.now(timezone.utc)
            duration = int(tmpl["duration_minutes"])
            completes_at = now + timedelta(minutes=duration)
            expedition = Expedition(
                id=uuid.uuid4(),
                user_id=user.discord_id,
                build_id=build_row.id,
                template_id=template,
                state=ExpeditionState.ACTIVE,
                started_at=now,
                completes_at=completes_at,
                correlation_id=uuid.uuid4(),
                scene_log=[],
            )
            session.add(expedition)
            await session.flush()

            for arche, row in crew_picks:
                session.add(
                    ExpeditionCrewAssignment(
                        expedition_id=expedition.id,
                        crew_id=row.id,
                        archetype=arche,
                    )
                )
                row.current_activity = CrewActivity.ON_EXPEDITION
                row.current_activity_id = expedition.id
            build_row.current_activity = BuildActivity.ON_EXPEDITION
            build_row.current_activity_id = expedition.id
            user.currency -= cost
            await session.flush()

            # 8. Schedule events + completion
            scheduled_scenes = _select_scheduled_scenes(tmpl, expedition.id)
            spacing = duration / max(len(scheduled_scenes) + 1, 2)
            jitter_pct = settings.EXPEDITION_EVENT_JITTER_PCT / 100.0
            rng = Random(str(expedition.id))
            for i, scene_id in enumerate(scheduled_scenes, start=1):
                offset_min = spacing * i
                jitter_min = offset_min * jitter_pct * (rng.random() * 2 - 1)
                fire_at = now + timedelta(minutes=offset_min + jitter_min)
                session.add(
                    ScheduledJob(
                        id=uuid.uuid4(),
                        user_id=user.discord_id,
                        job_type=JobType.EXPEDITION_EVENT,
                        payload={
                            "expedition_id": str(expedition.id),
                            "scene_id": scene_id,
                            "template_id": template,
                        },
                        scheduled_for=fire_at,
                        state=JobState.PENDING,
                    )
                )
            session.add(
                ScheduledJob(
                    id=uuid.uuid4(),
                    user_id=user.discord_id,
                    job_type=JobType.EXPEDITION_COMPLETE,
                    payload={
                        "expedition_id": str(expedition.id),
                        "template_id": template,
                    },
                    scheduled_for=completes_at,
                    state=JobState.PENDING,
                )
            )
            await session.flush()

        await interaction.response.send_message(
            f"**{tmpl.get('id', template)}** launched. ETA "
            f"{discord.utils.format_dt(completes_at, 'R')}.",
            ephemeral=True,
        )

    @expedition.command(name="status", description="Status of your active expeditions.")
    @app_commands.describe(expedition="Optional: a specific expedition id for the timeline view.")
    async def expedition_status(
        self,
        interaction: discord.Interaction,
        expedition: str | None = None,
    ) -> None:
        async with async_session() as session:
            user_id = str(interaction.user.id)
            if expedition is None:
                # List mode: all ACTIVE expeditions for this user.
                rows = (
                    (
                        await session.execute(
                            select(Expedition)
                            .where(Expedition.user_id == user_id)
                            .where(Expedition.state == ExpeditionState.ACTIVE)
                            .order_by(Expedition.completes_at)
                        )
                    )
                    .scalars()
                    .all()
                )
                if not rows:
                    await interaction.response.send_message(
                        "No active expeditions.",
                        ephemeral=True,
                    )
                    return
                user = await session.get(User, user_id)
                max_active = await get_max_expeditions(session, user) if user else len(rows)
                lines = [f"**Active expeditions** ({len(rows)} / {max_active} slots used)\n"]
                for ex in rows:
                    pending_count = sum(
                        1 for e in (ex.scene_log or []) if e.get("status") == "pending"
                    )
                    suffix = (
                        f" — {pending_count} event pending response now" if pending_count else ""
                    )
                    lines.append(
                        f"• `{ex.template_id}` — ETA "
                        f"{discord.utils.format_dt(ex.completes_at, 'R')}{suffix}"
                    )
                await interaction.response.send_message(
                    "\n".join(lines),
                    ephemeral=True,
                )
                return

            # Timeline mode
            try:
                exp_uuid = uuid.UUID(expedition)
            except ValueError:
                await interaction.response.send_message(
                    "Pick an expedition from the autocomplete list.",
                    ephemeral=True,
                )
                return
            ex = await session.get(Expedition, exp_uuid)
            if ex is None or ex.user_id != user_id:
                await interaction.response.send_message(
                    "Expedition not found.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                _render_timeline(ex),
                ephemeral=True,
            )

    @expedition.command(name="respond", description="Respond to a pending expedition event.")
    @app_commands.describe(
        expedition="Which expedition (defaults from autocomplete)",
        scene="Scene id with the pending event",
        choice="Choice id to commit",
    )
    async def expedition_respond(
        self,
        interaction: discord.Interaction,
        expedition: str,
        scene: str,
        choice: str,
    ) -> None:
        try:
            exp_uuid = uuid.UUID(expedition)
        except ValueError:
            await interaction.response.send_message(
                "Pick an expedition from the autocomplete list.",
                ephemeral=True,
            )
            return

        async with async_session() as session, session.begin():
            outcome = await handle_expedition_response(
                session,
                expedition_id=exp_uuid,
                scene_id=scene,
                choice_id=choice,
                invoking_user_id=str(interaction.user.id),
            )

        await interaction.response.send_message(
            _user_facing_message(outcome, choice),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Helpers shared with /expedition status + respond.
# ---------------------------------------------------------------------------


def _select_scheduled_scenes(tmpl: dict, expedition_id: uuid.UUID) -> list[str]:
    """Return the ordered list of scene_ids that get EXPEDITION_EVENT jobs."""
    if tmpl["kind"] == "scripted":
        return [
            s["id"] for s in tmpl.get("scenes", []) if s.get("choices") and not s.get("is_closing")
        ]
    pool = tmpl.get("events", [])
    n = int(tmpl.get("event_count", 1))
    rng = Random(str(expedition_id))
    sampled = rng.sample(pool, k=min(n, len(pool)))
    return [s["id"] for s in sampled]


async def _lookup_crew_by_display(
    session: AsyncSession, user_id: str, display: str
) -> CrewMember | None:
    """Match a 'First "Callsign" Last' display string to a crew row."""
    from sqlalchemy import select as sa_select

    result = await session.execute(sa_select(CrewMember).where(CrewMember.user_id == user_id))
    for row in result.scalars().all():
        if _format_display(row) == display:
            return row
    return None


def _format_display(crew: CrewMember) -> str:
    return f'{crew.first_name} "{crew.callsign}" {crew.last_name}'


def _render_timeline(ex: "Expedition") -> str:
    lines: list[str] = [
        f"**{ex.template_id}**",
        f"State: {ex.state.value}  ·  " f"ETA: {discord.utils.format_dt(ex.completes_at, 'R')}",
        "",
        "**Timeline**",
    ]
    if not ex.scene_log:
        lines.append("_(no scenes resolved yet)_")
    for entry in ex.scene_log or []:
        status = entry.get("status", "?")
        sid = entry.get("scene_id", "?")
        if status == "pending":
            lines.append(f"○ `{sid}` — pending response")
        elif status == "resolved":
            choice = entry.get("choice_id") or "default"
            outcome = "auto-resolved" if entry.get("auto_resolved") else f"chose {choice}"
            roll = entry.get("roll") or {}
            roll_note = ""
            if roll:
                roll_note = " (success)" if roll.get("success") else " (failure)"
            narr = entry.get("narrative", "")
            short = narr[:70] + "..." if len(narr) > 70 else narr
            lines.append(f"✓ `{sid}` — {outcome}{roll_note} — {short}")
        elif entry.get("kind") == "flag":
            lines.append(f"  · flag set: {entry.get('name')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cog setup hook
# ---------------------------------------------------------------------------


async def setup(bot: commands.Bot) -> None:
    if not settings.EXPEDITIONS_ENABLED:
        log.info("expeditions cog skipped — EXPEDITIONS_ENABLED is False")
        return
    await bot.add_cog(ExpeditionsCog(bot))
    bot.add_view(ExpeditionResponseView())
    log.info("expeditions cog loaded + persistent view registered")
