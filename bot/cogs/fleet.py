"""Fleet cog — Phase 2a slash commands for timers, stations, claims, notifications."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.metrics import currency_spent, timers_completed_total, timers_started_total
from bot.system_gating import get_active_system, system_required_message
from config.logging import get_logger
from config.settings import settings
from db.models import (
    CrewActivity,
    CrewMember,
    JobState,
    RewardSourceType,
    ScheduledJob,
    Timer,
    TimerState,
    TimerType,
    User,
)
from db.session import async_session
from engine.rewards import apply_reward
from engine.timer_recipes import RecipeNotFound, get_recipe, list_recipes
from scheduler.enqueue import enqueue_timer

log = get_logger(__name__)


# ──────────── helpers ────────────


async def _lookup_crew_by_display(
    session: AsyncSession, user_id: str, display_name: str
) -> CrewMember | None:
    m = re.match(r'^(.+?)\s+"(.+?)"\s+(.+)$', display_name.strip())
    if not m:
        return None
    first, callsign, last = m.group(1), m.group(2), m.group(3)
    result = await session.execute(
        select(CrewMember).where(
            CrewMember.user_id == user_id,
            CrewMember.first_name == first,
            CrewMember.last_name == last,
            CrewMember.callsign == callsign,
        )
    )
    return result.scalar_one_or_none()


async def _crew_idle_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete listing only idle crew."""
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    select(CrewMember).where(
                        CrewMember.user_id == str(interaction.user.id),
                        CrewMember.current_activity == CrewActivity.IDLE,
                    )
                )
            )
            .scalars()
            .all()
        )
    q = current.lower()
    out: list[app_commands.Choice[str]] = []
    for m in rows:
        name = f'{m.first_name} "{m.callsign}" {m.last_name}'
        if q in name.lower():
            out.append(app_commands.Choice(name=name[:100], value=name[:100]))
        if len(out) >= 25:
            break
    return out


def _routine_choices() -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(
            name=f"{r['name']} ({r['cost_credits']} Creds, {r['duration_minutes']}m)", value=r["id"]
        )
        for r in list_recipes(TimerType.TRAINING)
    ]


# ──────────── cog ────────────


class FleetCog(commands.Cog):
    """All Phase 2a fleet/training/research/build/stations/claim commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    training = app_commands.Group(name="training", description="Crew training routines")

    @training.command(name="start", description="Start a training routine on a crew member.")
    @app_commands.describe(crew="Which crew member to train", routine="Training routine to run")
    @app_commands.autocomplete(crew=_crew_idle_autocomplete)
    @app_commands.choices(routine=_routine_choices())
    async def training_start(
        self,
        interaction: discord.Interaction,
        crew: str,
        routine: str,
    ) -> None:
        sys = await get_active_system(interaction)
        if sys is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return

        try:
            recipe = get_recipe(TimerType.TRAINING, routine)
        except RecipeNotFound:
            await interaction.response.send_message("Unknown routine.", ephemeral=True)
            return

        async with async_session() as session, session.begin():
            user = await session.get(User, str(interaction.user.id), with_for_update=True)
            if user is None or user.currency < recipe["cost_credits"]:
                await interaction.response.send_message(
                    f"You need {recipe['cost_credits']} credits.",
                    ephemeral=True,
                )
                return
            crew_row = await _lookup_crew_by_display(session, user.discord_id, crew)
            if crew_row is None:
                await interaction.response.send_message("Crew member not found.", ephemeral=True)
                return
            if crew_row.current_activity != CrewActivity.IDLE:
                await interaction.response.send_message(
                    f"{crew_row.first_name} is currently {crew_row.current_activity.value}. "
                    "Free them first.",
                    ephemeral=True,
                )
                return

            now = datetime.now(timezone.utc)
            completes_at = now + timedelta(minutes=recipe["duration_minutes"])
            timer, _job = await enqueue_timer(
                session,
                user_id=user.discord_id,
                timer_type=TimerType.TRAINING,
                recipe_id=routine,
                completes_at=completes_at,
                payload={"crew_id": str(crew_row.id)},
            )
            user.currency -= recipe["cost_credits"]
            crew_row.current_activity = CrewActivity.TRAINING
            crew_row.current_activity_id = timer.id

        currency_spent.labels(reason="training").inc(recipe["cost_credits"])
        timers_started_total.labels(timer_type="training").inc()

        dur = recipe["duration_minutes"]
        await interaction.response.send_message(
            f"**{recipe['name']}** started for {crew}. Returns in {dur} minutes.",
            ephemeral=True,
        )

    @training.command(name="status", description="List your active and recent training timers.")
    async def training_status(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            active = (
                (
                    await session.execute(
                        select(Timer)
                        .where(Timer.user_id == str(interaction.user.id))
                        .where(Timer.timer_type == TimerType.TRAINING)
                        .where(Timer.state == TimerState.ACTIVE)
                        .order_by(Timer.completes_at)
                    )
                )
                .scalars()
                .all()
            )
        if not active:
            await interaction.response.send_message("No active training.", ephemeral=True)
            return
        lines = []
        for t in active:
            lines.append(
                f"• `{t.recipe_id}` — completes {discord.utils.format_dt(t.completes_at, 'R')}"
            )
        await interaction.response.send_message(
            "**Active training:**\n" + "\n".join(lines),
            ephemeral=True,
        )

    @training.command(
        name="cancel", description="Cancel an active training (50% credit refund, no XP)."
    )
    @app_commands.describe(crew="Which crew member's training to cancel")
    async def training_cancel(self, interaction: discord.Interaction, crew: str) -> None:
        async with async_session() as session, session.begin():
            crew_row = await _lookup_crew_by_display(session, str(interaction.user.id), crew)
            if crew_row is None or crew_row.current_activity != CrewActivity.TRAINING:
                await interaction.response.send_message(
                    "That crew member is not currently training.",
                    ephemeral=True,
                )
                return
            timer = await session.get(Timer, crew_row.current_activity_id, with_for_update=True)
            if timer is None or timer.state != TimerState.ACTIVE:
                await interaction.response.send_message(
                    "Training already completed.", ephemeral=True
                )
                return
            recipe = get_recipe(TimerType.TRAINING, timer.recipe_id)

            # Cancel the linked job atomically — only succeeds if still pending.
            from sqlalchemy import update as _upd

            result = await session.execute(
                _upd(ScheduledJob)
                .where(ScheduledJob.id == timer.linked_scheduled_job_id)
                .where(ScheduledJob.state == JobState.PENDING)
                .values(state=JobState.CANCELLED)
            )
            if (result.rowcount or 0) == 0:
                await interaction.response.send_message(
                    "Training is already firing — too late to cancel.",
                    ephemeral=True,
                )
                return

            refund = (recipe["cost_credits"] * settings.TIMER_CANCEL_REFUND_PCT) // 100
            await apply_reward(
                session,
                user_id=crew_row.user_id,
                source_type=RewardSourceType.TIMER_CANCEL_REFUND,
                source_id=f"timer_cancel_refund:{timer.id}",
                delta={"credits": refund},
            )
            timer.state = TimerState.CANCELLED
            crew_row.current_activity = CrewActivity.IDLE
            crew_row.current_activity_id = None

        timers_completed_total.labels(timer_type="training", outcome="cancelled").inc()
        await interaction.response.send_message(
            f"Training cancelled. Refunded {refund} credits.",
            ephemeral=True,
        )

    research = app_commands.Group(name="research", description="Fleet-wide research projects")

    @research.command(name="start", description="Start a research project (one active per pilot).")
    @app_commands.choices(
        project=[
            app_commands.Choice(
                name="Drive Tuning (200 Creds, 60m, +2% acceleration 48h)", value="drive_tuning"
            ),
            app_commands.Choice(
                name="Shield Calibration (250 Creds, 75m, +2% durability 48h)",
                value="shield_calibration",
            ),
            app_commands.Choice(
                name="Navigational Charting (300 Creds, 90m, +3% weather 48h)",
                value="nav_charting",
            ),
        ]
    )
    async def research_start(self, interaction: discord.Interaction, project: str) -> None:
        sys = await get_active_system(interaction)
        if sys is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return
        try:
            recipe = get_recipe(TimerType.RESEARCH, project)
        except RecipeNotFound:
            await interaction.response.send_message("Unknown project.", ephemeral=True)
            return
        async with async_session() as session, session.begin():
            user = await session.get(User, str(interaction.user.id), with_for_update=True)
            if user is None or user.currency < recipe["cost_credits"]:
                await interaction.response.send_message(
                    f"You need {recipe['cost_credits']} credits.",
                    ephemeral=True,
                )
                return
            now = datetime.now(timezone.utc)
            completes_at = now + timedelta(minutes=recipe["duration_minutes"])
            await enqueue_timer(
                session,
                user_id=user.discord_id,
                timer_type=TimerType.RESEARCH,
                recipe_id=project,
                completes_at=completes_at,
                payload={},
            )
            user.currency -= recipe["cost_credits"]
        currency_spent.labels(reason="research").inc(recipe["cost_credits"])
        timers_started_total.labels(timer_type="research").inc()
        await interaction.response.send_message(
            f"**{recipe['name']}** started. Completes in {recipe['duration_minutes']} minutes.",
            ephemeral=True,
        )

    @research.command(name="status", description="Status of your active research project.")
    async def research_status(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            t = (
                await session.execute(
                    select(Timer)
                    .where(Timer.user_id == str(interaction.user.id))
                    .where(Timer.timer_type == TimerType.RESEARCH)
                    .where(Timer.state == TimerState.ACTIVE)
                )
            ).scalar_one_or_none()
        if t is None:
            await interaction.response.send_message("No active research.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"**Active research:** `{t.recipe_id}` — "
            f"completes {discord.utils.format_dt(t.completes_at, 'R')}",
            ephemeral=True,
        )

    @research.command(name="cancel", description="Cancel your active research (50% credit refund).")
    async def research_cancel(self, interaction: discord.Interaction) -> None:
        await self._cancel_user_scoped_timer(interaction, TimerType.RESEARCH, "research")

    build = app_commands.Group(name="build", description="Ship construction recipes")

    @build.command(
        name="construct", description="Start a ship-build recipe (one active per pilot)."
    )
    @app_commands.choices(
        recipe=[
            app_commands.Choice(
                name="Salvage Reconstruction (500 Creds, 120m, 1 hauler hull)",
                value="salvage_reconstruction",
            ),
        ]
    )
    async def build_construct(self, interaction: discord.Interaction, recipe: str) -> None:
        sys = await get_active_system(interaction)
        if sys is None:
            await interaction.response.send_message(system_required_message(), ephemeral=True)
            return
        try:
            r = get_recipe(TimerType.SHIP_BUILD, recipe)
        except RecipeNotFound:
            await interaction.response.send_message("Unknown recipe.", ephemeral=True)
            return
        async with async_session() as session, session.begin():
            user = await session.get(User, str(interaction.user.id), with_for_update=True)
            if user is None or user.currency < r["cost_credits"]:
                await interaction.response.send_message(
                    f"You need {r['cost_credits']} credits.",
                    ephemeral=True,
                )
                return
            now = datetime.now(timezone.utc)
            await enqueue_timer(
                session,
                user_id=user.discord_id,
                timer_type=TimerType.SHIP_BUILD,
                recipe_id=recipe,
                completes_at=now + timedelta(minutes=r["duration_minutes"]),
                payload={},
            )
            user.currency -= r["cost_credits"]
        currency_spent.labels(reason="ship_build").inc(r["cost_credits"])
        timers_started_total.labels(timer_type="ship_build").inc()
        await interaction.response.send_message(
            f"**{r['name']}** started. Slipway hum-time: {r['duration_minutes']} minutes.",
            ephemeral=True,
        )

    @build.command(name="status", description="Status of your active ship-build.")
    async def build_status(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            t = (
                await session.execute(
                    select(Timer)
                    .where(Timer.user_id == str(interaction.user.id))
                    .where(Timer.timer_type == TimerType.SHIP_BUILD)
                    .where(Timer.state == TimerState.ACTIVE)
                )
            ).scalar_one_or_none()
        if t is None:
            await interaction.response.send_message("No active ship-build.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"**Active ship-build:** `{t.recipe_id}` — "
            f"completes {discord.utils.format_dt(t.completes_at, 'R')}",
            ephemeral=True,
        )

    @build.command(name="cancel", description="Cancel your active ship-build (50% credit refund).")
    async def build_cancel(self, interaction: discord.Interaction) -> None:
        await self._cancel_user_scoped_timer(interaction, TimerType.SHIP_BUILD, "ship_build")

    async def _cancel_user_scoped_timer(
        self, interaction: discord.Interaction, ttype: TimerType, label: str
    ) -> None:
        async with async_session() as session, session.begin():
            t = (
                await session.execute(
                    select(Timer)
                    .where(Timer.user_id == str(interaction.user.id))
                    .where(Timer.timer_type == ttype)
                    .where(Timer.state == TimerState.ACTIVE)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if t is None:
                await interaction.response.send_message(
                    f"No active {label} to cancel.",
                    ephemeral=True,
                )
                return
            recipe = get_recipe(ttype, t.recipe_id)
            from sqlalchemy import update as _upd

            result = await session.execute(
                _upd(ScheduledJob)
                .where(ScheduledJob.id == t.linked_scheduled_job_id)
                .where(ScheduledJob.state == JobState.PENDING)
                .values(state=JobState.CANCELLED)
            )
            if (result.rowcount or 0) == 0:
                await interaction.response.send_message(
                    f"{label.title()} is already firing — too late to cancel.",
                    ephemeral=True,
                )
                return
            refund = (recipe["cost_credits"] * settings.TIMER_CANCEL_REFUND_PCT) // 100
            await apply_reward(
                session,
                user_id=t.user_id,
                source_type=RewardSourceType.TIMER_CANCEL_REFUND,
                source_id=f"timer_cancel_refund:{t.id}",
                delta={"credits": refund},
            )
            t.state = TimerState.CANCELLED
        timers_completed_total.labels(timer_type=ttype.value, outcome="cancelled").inc()
        await interaction.response.send_message(
            f"{label.title()} cancelled. Refunded {refund} credits.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FleetCog(bot))
