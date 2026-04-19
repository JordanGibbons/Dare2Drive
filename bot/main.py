"""Dare2Drive Discord bot entry point."""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands
from opentelemetry import trace
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from prometheus_client import start_http_server

from api.metrics import bot_command_errors, bot_commands_invoked
from config.logging import get_logger, setup_logging
from config.metrics import trace_exemplar
from config.settings import settings
from config.tracing import init_tracing
from db.session import async_session, engine

setup_logging()
log = get_logger(__name__)

init_tracing("Dare2Drive")
SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
tracer = trace.get_tracer(__name__)


class TutorialCommandTree(app_commands.CommandTree):
    """CommandTree subclass that gates commands during the tutorial."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        from bot.cogs.tutorial import get_blocked_message, is_command_allowed
        from db.models import User

        if not interaction.command:
            return True

        command_name = interaction.command.name

        with tracer.start_as_current_span(f"discord.command.{command_name}") as span:
            span.set_attribute("discord.command", command_name)
            span.set_attribute("discord.user_id", str(interaction.user.id))

            log.info("command invoked: command=%s user=%s", command_name, interaction.user.id)
            bot_commands_invoked.labels(command=command_name).inc(exemplar=trace_exemplar())

            async with async_session() as session:
                user = await session.get(User, str(interaction.user.id))

            if not user:
                return True

            if is_command_allowed(user, command_name):
                return True

            span.set_attribute("discord.blocked", True)
            msg = get_blocked_message(user, command_name)
            await interaction.response.send_message(msg, ephemeral=True)
            return False

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        command_name = interaction.command.name if interaction.command else "unknown"
        with tracer.start_as_current_span(f"discord.command.{command_name}.error") as span:
            span.set_attribute("discord.command", command_name)
            span.record_exception(error)
            bot_command_errors.labels(command=command_name).inc(exemplar=trace_exemplar())
            log.error(
                "App command error: command=%s user=%s",
                command_name,
                interaction.user.id,
                exc_info=error,
            )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "Something went wrong. Try again.", ephemeral=True
            )


class Dare2DriveBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, tree_cls=TutorialCommandTree)

    async def setup_hook(self) -> None:
        """Load all cog extensions."""
        from sqlalchemy import func, select

        from api.metrics import users_registered
        from db.models import TutorialStep, User

        async with async_session() as session:
            result = await session.execute(
                select(func.count()).where(User.tutorial_step == TutorialStep.COMPLETE)
            )
            users_registered.set(result.scalar_one())

        cog_modules = [
            "bot.cogs.tutorial",
            "bot.cogs.cards",
            "bot.cogs.garage",
            "bot.cogs.race",
            "bot.cogs.market",
            "bot.cogs.admin",
        ]
        for module in cog_modules:
            await self.load_extension(module)
            log.info("Loaded cog: %s", module)

        if settings.DISCORD_GUILD_ID:
            guild = discord.Object(id=int(settings.DISCORD_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            try:
                await self.tree.sync(guild=guild)
                log.info("Synced commands to guild %s", settings.DISCORD_GUILD_ID)
            except discord.errors.Forbidden:
                log.warning(
                    "Cannot sync commands to guild %s — bot may not be a member yet. "
                    "Invite the bot using the OAuth2 URL with the 'applications.commands' scope.",
                    settings.DISCORD_GUILD_ID,
                )
        else:
            await self.tree.sync()
            log.info("Synced commands globally")

    async def on_ready(self) -> None:
        log.info("Bot online as %s (ID: %s)", self.user, self.user.id if self.user else "?")


async def main() -> None:
    start_http_server(8001)
    log.info("Bot metrics server started on port 8001")
    bot = Dare2DriveBot()
    async with bot:
        await bot.start(settings.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
