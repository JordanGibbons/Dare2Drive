"""Hiring cog — /dossier, /hire, /crew, /assign, /unassign."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from api.metrics import crew_recruited, currency_spent, dossier_purchased
from bot.cogs.cards import _PackRevealView
from bot.reveal import CrewRevealEntry
from bot.system_gating import get_active_system, system_required_message
from config.logging import get_logger
from config.metrics import trace_exemplar
from config.tracing import traced_command
from db.models import User
from db.session import async_session
from engine.crew_recruit import InsufficientCreditsError, recruit_crew_from_dossier
from engine.stat_resolver import _get_archetype_mapping

log = get_logger(__name__)

_DOSSIER_TIERS = ("recruit_lead", "dossier", "elite_dossier")
_TIER_PRICES = {"recruit_lead": 150, "dossier": 500, "elite_dossier": 1500}
_TIER_DISPLAY = {
    "recruit_lead": "Recruit Lead",
    "dossier": "Dossier",
    "elite_dossier": "Elite Dossier",
}


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
        crew_recruited.labels(source="dossier", archetype=archetype, rarity=rarity).inc(
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
        await interaction.response.send_message("Not implemented yet.", ephemeral=True)

    @app_commands.command(name="crew", description="View your crew roster.")
    @traced_command
    async def crew(self, interaction: discord.Interaction, filter: str | None = None) -> None:
        await interaction.response.send_message("Not implemented yet.", ephemeral=True)

    @app_commands.command(name="assign", description="Assign a crew member to your active build.")
    @traced_command
    async def assign(self, interaction: discord.Interaction, crew: str) -> None:
        await interaction.response.send_message("Not implemented yet.", ephemeral=True)

    @app_commands.command(name="unassign", description="Remove a crew member from your build.")
    @traced_command
    async def unassign(self, interaction: discord.Interaction, crew: str) -> None:
        await interaction.response.send_message("Not implemented yet.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HiringCog(bot))
