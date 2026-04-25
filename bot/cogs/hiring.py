"""Hiring cog — /dossier, /hire, /crew, /assign, /unassign."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.metrics import crew_assignment, crew_recruited, currency_spent, dossier_purchased
from bot.cogs.cards import _PackRevealView
from bot.reveal import CrewRevealEntry
from bot.system_gating import get_active_system, system_required_message
from config.logging import get_logger
from config.metrics import trace_exemplar
from config.tracing import traced_command
from db.models import Build, CrewAssignment, CrewDailyLead, CrewMember, User
from db.session import async_session
from engine.crew_recruit import (
    InsufficientCreditsError,
    LeadAlreadyClaimedError,
    recruit_crew_from_daily_lead,
    recruit_crew_from_dossier,
)
from engine.stat_resolver import _get_archetype_mapping

log = get_logger(__name__)

_DOSSIER_TIERS = ("recruit_lead", "dossier", "elite_dossier")
_TIER_PRICES = {"recruit_lead": 150, "dossier": 500, "elite_dossier": 1500}
_TIER_DISPLAY = {
    "recruit_lead": "Recruit Lead",
    "dossier": "Dossier",
    "elite_dossier": "Elite Dossier",
}

_ARCHETYPE_EMOJI = {
    "pilot": "🧑‍✈️",
    "engineer": "🔧",
    "gunner": "🔫",
    "navigator": "🧭",
    "medic": "🩹",
}
_RARITY_EMOJI = {
    "common": "⬜",
    "uncommon": "🟩",
    "rare": "🟦",
    "epic": "🟪",
    "legendary": "🟨",
    "ghost": "👻",
}


def _format_crew_line(member: CrewMember, assigned: bool) -> str:
    emoji = _ARCHETYPE_EMOJI[member.archetype.value]
    rarity_emoji = _RARITY_EMOJI[member.rarity.value]
    name = f'{member.first_name} "{member.callsign}" {member.last_name}'
    tag = " *(assigned)*" if assigned else ""
    return (
        f"{emoji} {rarity_emoji} **{name}** — {member.archetype.value.title()} L{member.level}{tag}"
    )


async def _crew_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for /crew_inspect, /assign, /unassign — used by Tasks 14, 15."""
    async with async_session() as session:
        result = await session.execute(
            select(CrewMember).where(CrewMember.user_id == str(interaction.user.id))
        )
        members = list(result.scalars().all())
    q = current.lower()
    out: list[app_commands.Choice[str]] = []
    for m in members:
        name = f'{m.first_name} "{m.callsign}" {m.last_name}'
        if q in name.lower():
            out.append(app_commands.Choice(name=name[:100], value=name[:100]))
        if len(out) >= 25:
            break
    return out


async def _lookup_crew_by_display(
    session: AsyncSession, user_id: str, display_name: str
) -> CrewMember | None:
    """Parse 'First "Callsign" Last' and look up the crew member."""
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


class HiringCog(commands.Cog):
    """Crew recruitment, listing, and assignment."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="dossier", description="Buy a dossier and recruit a crew member.")
    @app_commands.describe(tier="Which dossier tier to purchase")
    @app_commands.choices(
        tier=[
            app_commands.Choice(name="Recruit Lead (150 Creds)", value="recruit_lead"),
            app_commands.Choice(name="Dossier (500 Creds)", value="dossier"),
            app_commands.Choice(name="Elite Dossier (1500 Creds)", value="elite_dossier"),
        ]
    )
    @traced_command
    async def dossier(self, interaction: discord.Interaction, tier: str) -> None:
        if tier not in _DOSSIER_TIERS:
            await interaction.response.send_message("Invalid tier.", ephemeral=True)
            return

        async with async_session() as session:
            system = await get_active_system(interaction, session)
            if system is None:
                await interaction.response.send_message(system_required_message(), ephemeral=True)
                return

            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            try:
                member = await recruit_crew_from_dossier(session, user, tier)
            except InsufficientCreditsError:
                await interaction.response.send_message(
                    "Not enough Creds for this dossier.", ephemeral=True
                )
                return

            mapping = _get_archetype_mapping()[member.archetype.value]
            display_name = _TIER_DISPLAY[tier]
            archetype = member.archetype.value
            rarity = member.rarity.value
            primary_stat = mapping["primary"]
            secondary_stat = mapping["secondary"]
            crew_full_name = f'{member.first_name} "{member.callsign}" {member.last_name}'
            level = member.level

            await session.commit()

        dossier_purchased.labels(tier=tier).inc(exemplar=trace_exemplar())
        crew_recruited.labels(source="dossier", tier=tier, archetype=archetype, rarity=rarity).inc(
            exemplar=trace_exemplar()
        )
        currency_spent.labels(reason=f"dossier_{tier}").inc(
            _TIER_PRICES[tier], exemplar=trace_exemplar()
        )

        entry = CrewRevealEntry(
            name=crew_full_name,
            rarity=rarity,
            archetype=archetype,
            level=level,
            primary_stat=primary_stat,
            secondary_stat=secondary_stat,
        )
        view = _PackRevealView(
            entries=[entry],
            display_name=display_name,
            owner_id=interaction.user.id,
        )
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @app_commands.command(name="hire", description="Claim today's free crew lead.")
    @traced_command
    async def hire(self, interaction: discord.Interaction) -> None:
        user_id = str(interaction.user.id)
        async with async_session() as session:
            system = await get_active_system(interaction, session)
            if system is None:
                await interaction.response.send_message(system_required_message(), ephemeral=True)
                return

            user = await session.get(User, user_id)
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            today = datetime.now(timezone.utc).date()
            lead = await session.get(CrewDailyLead, (user_id, today))
            if lead is None:
                await interaction.response.send_message(
                    "No lead today — run `/daily` first to see today's candidate.",
                    ephemeral=True,
                )
                return
            if lead.claimed_at is not None:
                await interaction.response.send_message(
                    "You've already hired today's lead.", ephemeral=True
                )
                return

            try:
                member = await recruit_crew_from_daily_lead(session, user, lead)
            except LeadAlreadyClaimedError:
                await interaction.response.send_message("Lead already claimed.", ephemeral=True)
                return

            mapping = _get_archetype_mapping()[member.archetype.value]
            archetype = member.archetype.value
            rarity = member.rarity.value
            crew_full_name = f'{member.first_name} "{member.callsign}" {member.last_name}'
            level = member.level
            primary_stat = mapping["primary"]
            secondary_stat = mapping["secondary"]

            await session.commit()

        crew_recruited.labels(
            source="daily_lead", tier="daily_lead", archetype=archetype, rarity=rarity
        ).inc(exemplar=trace_exemplar())

        entry = CrewRevealEntry(
            name=crew_full_name,
            rarity=rarity,
            archetype=archetype,
            level=level,
            primary_stat=primary_stat,
            secondary_stat=secondary_stat,
        )
        view = _PackRevealView(
            entries=[entry], display_name="Today's Lead", owner_id=interaction.user.id
        )
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @app_commands.command(name="crew", description="View your crew roster.")
    @app_commands.describe(
        filter="Optional filter: all, unassigned, assigned, or an archetype name."
    )
    @app_commands.choices(
        filter=[
            app_commands.Choice(name="All", value="all"),
            app_commands.Choice(name="Unassigned", value="unassigned"),
            app_commands.Choice(name="Assigned", value="assigned"),
            app_commands.Choice(name="Pilot", value="pilot"),
            app_commands.Choice(name="Engineer", value="engineer"),
            app_commands.Choice(name="Gunner", value="gunner"),
            app_commands.Choice(name="Navigator", value="navigator"),
            app_commands.Choice(name="Medic", value="medic"),
        ]
    )
    @traced_command
    async def crew(self, interaction: discord.Interaction, filter: str | None = None) -> None:
        """Universe-wide roster — no system gating."""
        user_id = str(interaction.user.id)
        async with async_session() as session:
            members_q = await session.execute(
                select(CrewMember).where(CrewMember.user_id == user_id)
            )
            members = list(members_q.scalars().all())
            if not members:
                await interaction.response.send_message(
                    "No crew yet — try `/dossier` or `/hire`.", ephemeral=True
                )
                return

            assigned_q = await session.execute(
                select(CrewAssignment.crew_id).where(
                    CrewAssignment.crew_id.in_([m.id for m in members])
                )
            )
            assigned_ids = {row[0] for row in assigned_q.all()}

        f = (filter or "all").lower()
        if f == "unassigned":
            members = [m for m in members if m.id not in assigned_ids]
        elif f == "assigned":
            members = [m for m in members if m.id in assigned_ids]
        elif f in {"pilot", "engineer", "gunner", "navigator", "medic"}:
            members = [m for m in members if m.archetype.value == f]
        # else: all — no filter

        if not members:
            await interaction.response.send_message(f"No crew match filter `{f}`.", ephemeral=True)
            return

        rarity_order = {
            "ghost": 0,
            "legendary": 1,
            "epic": 2,
            "rare": 3,
            "uncommon": 4,
            "common": 5,
        }
        members.sort(
            key=lambda m: (
                rarity_order.get(m.rarity.value, 99),
                -m.level,
                m.first_name,
            )
        )

        lines = [_format_crew_line(m, m.id in assigned_ids) for m in members[:25]]

        embed = discord.Embed(
            title=f"🛰️ Crew Roster — {len(members)} total",
            description="\n".join(lines),
            color=0x3B82F6,
        )
        if len(members) > 25:
            embed.set_footer(text=f"Showing 25 of {len(members)}. Use filters to narrow.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="crew_inspect", description="Inspect a crew member.")
    @app_commands.describe(name="Crew member name")
    @app_commands.autocomplete(name=_crew_name_autocomplete)
    @traced_command
    async def crew_inspect(self, interaction: discord.Interaction, name: str) -> None:
        """Universe-wide crew inspection — no system gating."""
        from engine.crew_xp import xp_for_next

        user_id = str(interaction.user.id)
        async with async_session() as session:
            member = await _lookup_crew_by_display(session, user_id, name)
            if member is None:
                await interaction.response.send_message(f"No crew named `{name}`.", ephemeral=True)
                return

            assigned_q = await session.execute(
                select(CrewAssignment).where(CrewAssignment.crew_id == member.id)
            )
            assignment = assigned_q.scalar_one_or_none()

            archetype = member.archetype.value
            rarity = member.rarity.value
            display = f'{member.first_name} "{member.callsign}" {member.last_name}'
            level = member.level
            xp = member.xp
            acquired_at = member.acquired_at
            is_assigned = assignment is not None

        mapping = _get_archetype_mapping()[archetype]
        arch_emoji = _ARCHETYPE_EMOJI[archetype]
        rarity_emoji = _RARITY_EMOJI[rarity]

        embed = discord.Embed(
            title=f"{arch_emoji} {display}",
            description=f"{rarity_emoji} **{rarity.title()}** {archetype.title()}",
            color=0x3B82F6,
        )
        embed.add_field(name="Level", value=f"L{level}", inline=True)
        if level >= 10:
            embed.add_field(name="XP", value="MAX", inline=True)
        else:
            embed.add_field(
                name="XP",
                value=f"{xp} / {xp_for_next(level)}",
                inline=True,
            )

        primary_display = mapping["primary"].replace("effective_", "").replace("_", " ")
        secondary_display = mapping["secondary"].replace("effective_", "").replace("_", " ")
        embed.add_field(
            name="Boosts",
            value=(f"**Primary:** {primary_display}\n**Secondary:** {secondary_display}"),
            inline=False,
        )
        embed.add_field(
            name="Assigned",
            value=("Yes" if is_assigned else "In quarters"),
            inline=True,
        )
        embed.set_footer(text=f"Acquired {acquired_at.strftime('%Y-%m-%d')}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="assign", description="Assign a crew member to your active build.")
    @app_commands.describe(crew="Crew member name")
    @app_commands.autocomplete(crew=_crew_name_autocomplete)
    @traced_command
    async def assign(self, interaction: discord.Interaction, crew: str) -> None:
        user_id = str(interaction.user.id)
        prior_name: str | None = None
        auto_unassigned = False
        async with async_session() as session:
            system = await get_active_system(interaction, session)
            if system is None:
                await interaction.response.send_message(system_required_message(), ephemeral=True)
                return

            member = await _lookup_crew_by_display(session, user_id, crew)
            if member is None:
                await interaction.response.send_message(f"No crew named `{crew}`.", ephemeral=True)
                return

            build_q = await session.execute(
                select(Build).where(Build.user_id == user_id, Build.is_active.is_(True)).limit(1)
            )
            build = build_q.scalar_one_or_none()
            if build is None:
                await interaction.response.send_message(
                    "You don't have an active build. Use `/hangar` to create one.",
                    ephemeral=True,
                )
                return

            # Remove any existing assignment of THIS crew (covers re-assign across builds)
            existing_q = await session.execute(
                select(CrewAssignment).where(CrewAssignment.crew_id == member.id)
            )
            existing = existing_q.scalar_one_or_none()
            if existing is not None:
                await session.delete(existing)
                await session.flush()

            # Auto-unassign any prior same-archetype crew on THIS build
            prior_q = await session.execute(
                select(CrewAssignment).where(
                    CrewAssignment.build_id == build.id,
                    CrewAssignment.archetype == member.archetype,
                )
            )
            prior = prior_q.scalar_one_or_none()
            if prior is not None:
                prior_member = await session.get(CrewMember, prior.crew_id)
                if prior_member is not None:
                    prior_name = (
                        f'{prior_member.first_name} "{prior_member.callsign}" '
                        f"{prior_member.last_name}"
                    )
                await session.delete(prior)
                await session.flush()
                auto_unassigned = True

            session.add(
                CrewAssignment(
                    crew_id=member.id,
                    build_id=build.id,
                    archetype=member.archetype,
                )
            )

            display = f'{member.first_name} "{member.callsign}" {member.last_name}'
            archetype_title = member.archetype.value.title()

            await session.commit()

        if auto_unassigned:
            crew_assignment.labels(action="auto_unassign").inc()
        crew_assignment.labels(action="assign").inc()
        msg = f"Assigned **{display}** as {archetype_title}."
        if prior_name:
            msg += f" (Replaced {prior_name}.)"
        await interaction.response.send_message(msg)

    @app_commands.command(name="unassign", description="Remove a crew member from your build.")
    @app_commands.describe(crew="Crew member name")
    @app_commands.autocomplete(crew=_crew_name_autocomplete)
    @traced_command
    async def unassign(self, interaction: discord.Interaction, crew: str) -> None:
        user_id = str(interaction.user.id)
        async with async_session() as session:
            system = await get_active_system(interaction, session)
            if system is None:
                await interaction.response.send_message(system_required_message(), ephemeral=True)
                return

            member = await _lookup_crew_by_display(session, user_id, crew)
            if member is None:
                await interaction.response.send_message(f"No crew named `{crew}`.", ephemeral=True)
                return

            assignment_q = await session.execute(
                select(CrewAssignment).where(CrewAssignment.crew_id == member.id)
            )
            assignment = assignment_q.scalar_one_or_none()
            if assignment is None:
                await interaction.response.send_message(f"`{crew}` isn't assigned.", ephemeral=True)
                return

            await session.delete(assignment)
            display = f'{member.first_name} "{member.callsign}" {member.last_name}'
            await session.commit()

        crew_assignment.labels(action="unassign").inc()
        await interaction.response.send_message(f"Unassigned **{display}** back to quarters.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HiringCog(bot))
