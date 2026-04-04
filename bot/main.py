"""Dare2Drive Discord bot entry point."""

from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

from config.logging import get_logger, setup_logging
from config.settings import settings

setup_logging()
log = get_logger(__name__)


class Dare2DriveBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        """Load all cog extensions."""
        cog_modules = [
            "bot.cogs.cards",
            "bot.cogs.garage",
            "bot.cogs.race",
            "bot.cogs.market",
        ]
        for module in cog_modules:
            await self.load_extension(module)
            log.info("Loaded cog: %s", module)

        if settings.DISCORD_GUILD_ID:
            guild = discord.Object(id=int(settings.DISCORD_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to guild %s", settings.DISCORD_GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Synced commands globally")

    async def on_ready(self) -> None:
        log.info("Bot online as %s (ID: %s)", self.user, self.user.id if self.user else "?")


async def main() -> None:
    bot = Dare2DriveBot()
    async with bot:
        await bot.start(settings.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
