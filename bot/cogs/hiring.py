"""Hiring cog — /dossier, /hire, /crew, /assign, /unassign."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from config.logging import get_logger
from config.tracing import traced_command

log = get_logger(__name__)


class HiringCog(commands.Cog):
    """Crew recruitment, listing, and assignment."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="dossier", description="Buy a dossier and recruit a crew member.")
    @traced_command
    async def dossier(self, interaction: discord.Interaction, tier: str) -> None:
        await interaction.response.send_message("Not implemented yet.", ephemeral=True)

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
