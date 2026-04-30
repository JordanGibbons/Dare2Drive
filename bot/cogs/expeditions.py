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

from api.metrics import expedition_active, expeditions_started_total
from bot.system_gating import get_active_system, system_required_message
from config.logging import get_logger
from config.settings import settings
from db.models import (
    Build,
    BuildActivity,
    CrewActivity,
    CrewAssignment,
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
    count_active_expeditions_for_user,
    get_max_expeditions,
)
from engine.expedition_custom_id import (
    CUSTOM_ID_PREFIX,
    build_custom_id,
    parse_custom_id,
)
from engine.expedition_template import (
    TemplateValidationError,
    load_template,
)

log = get_logger(__name__)

# Re-exports for backwards compat with any external import sites.
__all__ = ["CUSTOM_ID_PREFIX", "build_custom_id", "parse_custom_id"]


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
# Slash-command autocompletes — players never type IDs.
# ---------------------------------------------------------------------------

from pathlib import Path as _Path  # noqa: E402

_TEMPLATE_DIR = _Path(__file__).resolve().parents[2] / "data" / "expeditions"


def _humanize_id(template_id: str) -> str:
    """`outer_marker_patrol` → `Outer Marker Patrol`."""
    return template_id.replace("_", " ").title()


async def _template_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """List `data/expeditions/*.yaml` files. Player sees friendly names; value = template_id."""
    q = current.lower()
    out: list[app_commands.Choice[str]] = []
    for p in sorted(_TEMPLATE_DIR.glob("*.yaml")):
        tid = p.stem
        if q and q not in tid.lower() and q not in _humanize_id(tid).lower():
            continue
        label = f"{_humanize_id(tid)} ({tid})"[:100]
        out.append(app_commands.Choice(name=label, value=tid))
        if len(out) >= 25:
            break
    return out


async def _build_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """List the player's IDLE builds. Value is the build UUID; label is the build's name + hull."""
    user_id = str(interaction.user.id)
    q = current.lower()
    async with async_session() as session:
        result = await session.execute(
            select(Build)
            .where(Build.user_id == user_id)
            .where(Build.current_activity == BuildActivity.IDLE)
            .order_by(Build.name)
        )
        out: list[app_commands.Choice[str]] = []
        for b in result.scalars().all():
            label = f"{b.name} ({b.hull_class.value})"
            if q and q not in label.lower():
                continue
            out.append(app_commands.Choice(name=label[:100], value=str(b.id)))
            if len(out) >= 25:
                break
    return out


async def _active_expedition_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """List the player's ACTIVE expeditions for /expedition status + /expedition respond."""
    user_id = str(interaction.user.id)
    q = current.lower()
    async with async_session() as session:
        result = await session.execute(
            select(Expedition)
            .where(Expedition.user_id == user_id)
            .where(Expedition.state == ExpeditionState.ACTIVE)
            .order_by(Expedition.completes_at)
        )
        out: list[app_commands.Choice[str]] = []
        for ex in result.scalars().all():
            label = f"{_humanize_id(ex.template_id)} (ETA {ex.completes_at:%H:%M %m-%d})"
            if q and q not in label.lower():
                continue
            out.append(app_commands.Choice(name=label[:100], value=str(ex.id)))
            if len(out) >= 25:
                break
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
        template="Pick from the autocomplete list",
        build="Pick a ship from your fleet",
    )
    @app_commands.autocomplete(
        template=_template_autocomplete,
        build=_build_autocomplete,
    )
    async def expedition_start(
        self,
        interaction: discord.Interaction,
        template: str,
        build: str,
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
            current_active = await count_active_expeditions_for_user(session, user.discord_id)
            if current_active >= max_active:
                await interaction.response.send_message(
                    f"You're at the max active expedition limit ({current_active}/{max_active}). "
                    "Wait for one to complete.",
                    ephemeral=True,
                )
                return

            # 3. Build owned, IDLE
            try:
                build_uuid = uuid.UUID(build)
            except ValueError:
                await interaction.response.send_message(
                    "Pick a ship from the autocomplete list.", ephemeral=True
                )
                return
            build_row = await session.get(Build, build_uuid, with_for_update=True)
            if build_row is None or build_row.user_id != user.discord_id:
                await interaction.response.send_message("Build not found.", ephemeral=True)
                return
            if build_row.current_activity != BuildActivity.IDLE:
                await interaction.response.send_message(
                    f"`{build_row.name}` is currently busy and can't launch.",
                    ephemeral=True,
                )
                return

            # 4. Phase 2c: derive aboard set from crew_assignments
            aboard_rows = (
                await session.execute(
                    select(CrewAssignment, CrewMember)
                    .join(CrewMember, CrewAssignment.crew_id == CrewMember.id)
                    .where(CrewAssignment.build_id == build_row.id)
                )
            ).all()

            now = datetime.now(timezone.utc)
            idle_aboard: list[tuple[CrewAssignment, CrewMember]] = []
            for assignment, crew in aboard_rows:
                is_busy = crew.current_activity != CrewActivity.IDLE
                is_injured = crew.injured_until is not None and crew.injured_until > now
                if not is_busy and not is_injured:
                    idle_aboard.append((assignment, crew))

            # 5. Validate against template's crew_required
            archetypes_aboard = {a.archetype.name for a, _ in idle_aboard}  # uppercase like "PILOT"
            crew_req = tmpl.get("crew_required", {})
            min_required = int(crew_req.get("min", 1))
            archetypes_any = set(crew_req.get("archetypes_any", []))
            archetypes_all = set(crew_req.get("archetypes_all", []))

            satisfies_min = len(idle_aboard) >= min_required
            satisfies_any = (not archetypes_any) or bool(archetypes_aboard & archetypes_any)
            satisfies_all = archetypes_all <= archetypes_aboard
            if not satisfies_min or not satisfies_any or not satisfies_all:
                error_lines = _format_crew_required_error(
                    template_id=template,
                    template_label=tmpl.get("id", template),
                    archetypes_any=archetypes_any,
                    min_required=min_required,
                    build_row=build_row,
                    aboard_rows=aboard_rows,
                    now=now,
                )
                await interaction.response.send_message("\n".join(error_lines), ephemeral=True)
                return

            # 6. Cost check
            cost = int(tmpl.get("cost_credits", 0))
            if user.currency < cost:
                await interaction.response.send_message(
                    f"You need {cost} credits to launch — you have {user.currency}.",
                    ephemeral=True,
                )
                return

            # 7. Atomic creation
            now_utc = datetime.now(timezone.utc)
            duration = int(tmpl["duration_minutes"])
            completes_at = now_utc + timedelta(minutes=duration)
            expedition = Expedition(
                id=uuid.uuid4(),
                user_id=user.discord_id,
                build_id=build_row.id,
                template_id=template,
                state=ExpeditionState.ACTIVE,
                started_at=now_utc,
                completes_at=completes_at,
                correlation_id=uuid.uuid4(),
                scene_log=[],
            )
            session.add(expedition)

            # Snapshot idle aboard members into ExpeditionCrewAssignment
            for assignment, crew in idle_aboard:
                session.add(
                    ExpeditionCrewAssignment(
                        expedition_id=expedition.id,
                        crew_id=crew.id,
                        archetype=assignment.archetype,
                    )
                )
                crew.current_activity = CrewActivity.ON_EXPEDITION
                crew.current_activity_id = expedition.id

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
                fire_at = now_utc + timedelta(minutes=offset_min + jitter_min)
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

        expeditions_started_total.labels(template_id=template, kind=tmpl["kind"]).inc()
        expedition_active.inc()

        await interaction.response.send_message(
            f"**{tmpl.get('id', template)}** launched. ETA "
            f"{discord.utils.format_dt(completes_at, 'R')}.",
            ephemeral=True,
        )

    @expedition.command(name="status", description="Status of your active expeditions.")
    @app_commands.describe(expedition="Optional: pick one for the timeline view.")
    @app_commands.autocomplete(expedition=_active_expedition_autocomplete)
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
        expedition="Pick from your active expeditions",
        scene="Scene id with the pending event",
        choice="Choice id to commit",
    )
    @app_commands.autocomplete(expedition=_active_expedition_autocomplete)
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


def _format_crew_required_error(
    *,
    template_id: str,
    template_label: str,
    archetypes_any: set[str],
    min_required: int,
    build_row: Build,
    aboard_rows: list,
    now: datetime,
) -> list[str]:
    """Return the multi-line `/expedition start` error message walking every slot."""
    from engine.class_engine import slots_for_hull

    lines: list[str] = []
    if archetypes_any:
        sorted_any = sorted(archetypes_any)
        lines.append(
            f"**{template_label}** needs at least {min_required} of "
            f"{{{', '.join(sorted_any)}}}."
        )
    else:
        lines.append(f"**{template_label}** needs at least {min_required} idle aboard crew.")
    lines.append(f"`{build_row.name}` ({build_row.hull_class.value.title()}):")

    aboard_by_archetype = {a.archetype: c for a, c in aboard_rows}
    for slot_archetype in slots_for_hull(build_row.hull_class):
        crew = aboard_by_archetype.get(slot_archetype)
        if crew is None:
            lines.append(f"  • **{slot_archetype.name}** — empty")
        else:
            display = f'{crew.first_name} "{crew.callsign}" {crew.last_name}'
            if crew.injured_until is not None and crew.injured_until > now:
                returns_at = discord.utils.format_dt(crew.injured_until, "R")
                lines.append(
                    f"  • **{slot_archetype.name}** — {display} "
                    f"(injured, recovers {returns_at})"
                )
            elif crew.current_activity != CrewActivity.IDLE:
                lines.append(
                    f"  • **{slot_archetype.name}** — {display} " f"({crew.current_activity.value})"
                )
            else:
                lines.append(f"  • **{slot_archetype.name}** — {display} (idle)")
    lines.append("Assign crew via `/hangar` or wait for busy crew to free up.")
    return lines


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
