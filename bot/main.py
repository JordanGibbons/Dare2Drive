"""Dare2Drive Discord bot entry point."""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands
from opentelemetry import trace
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from prometheus_client import start_http_server
from sqlalchemy import select

from api.metrics import bot_command_errors, bot_commands_invoked
from config.logging import get_logger, setup_logging
from config.metrics import trace_exemplar
from config.settings import settings
from config.tracing import init_tracing
from db.models import Sector
from db.session import async_session, engine

setup_logging()
log = get_logger(__name__)


async def register_sector_for_guild(guild, session) -> Sector:
    """Insert a Sector row for this guild if not already present. Idempotent."""
    existing = await session.execute(select(Sector).where(Sector.guild_id == str(guild.id)))
    sys = existing.scalar_one_or_none()
    if sys is not None:
        return sys
    sys = Sector(
        guild_id=str(guild.id),
        name=guild.name,
        owner_discord_id=str(guild.owner_id) if guild.owner_id else "0",
    )
    session.add(sys)
    await session.flush()
    await session.refresh(sys)
    return sys


async def reconcile_sectors_with_guilds(guilds, session) -> None:
    """Ensure every current guild has a Sector row. Call on bot startup."""
    for guild in guilds:
        await register_sector_for_guild(guild, session)


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

        # Use qualified_name everywhere — it includes any parent Group
        # (e.g. "training start"). Leaf-only matching would let /training start
        # bypass gating because "start" is in ALWAYS_ALLOWED for the top-level
        # /start command.
        qualified_name = interaction.command.qualified_name

        with tracer.start_as_current_span(
            f"discord.command.{qualified_name.replace(' ', '.')}"
        ) as span:
            span.set_attribute("discord.command", qualified_name)
            span.set_attribute("discord.user_id", str(interaction.user.id))

            log.info("command invoked: command=%s user=%s", qualified_name, interaction.user.id)
            bot_commands_invoked.labels(command=qualified_name).inc(exemplar=trace_exemplar())

            async with async_session() as session:
                user = await session.get(User, str(interaction.user.id))

            if not user:
                return True

            if is_command_allowed(user, qualified_name):
                return True

            span.set_attribute("discord.blocked", True)
            msg = get_blocked_message(user, qualified_name)
            await interaction.response.send_message(msg, ephemeral=True)
            return False

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        qualified_name = interaction.command.qualified_name if interaction.command else "unknown"
        with tracer.start_as_current_span(
            f"discord.command.{qualified_name.replace(' ', '.')}.error"
        ) as span:
            span.set_attribute("discord.command", qualified_name)
            span.record_exception(error)
            bot_command_errors.labels(command=qualified_name).inc(exemplar=trace_exemplar())
            log.error(
                "App command error: command=%s user=%s",
                qualified_name,
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
            "bot.cogs.hangar",
            "bot.cogs.hiring",
            "bot.cogs.race",
            "bot.cogs.market",
            "bot.cogs.admin",
            "bot.cogs.fleet",
            "bot.cogs.expeditions",  # Phase 2b — gated by settings.EXPEDITIONS_ENABLED
        ]
        for module in cog_modules:
            await self.load_extension(module)
            log.info("Loaded cog: %s", module)

        # Phase 2a — start the notification consumer.
        import redis.asyncio as _redis_async

        from bot.notifications import NotificationConsumer

        self._notif_redis = _redis_async.from_url(settings.REDIS_URL, decode_responses=True)
        self._notif_consumer = NotificationConsumer(
            bot=self,
            redis=self._notif_redis,
        )
        self._notif_task = asyncio.create_task(
            self._notif_consumer.run(),
            name="notification_consumer",
        )
        log.info("notification_consumer_started")

        # Phase 2b expedition handlers (registers via side-effect import)
        import scheduler.jobs.expedition_auto_resolve as _expedition_auto_resolve_module  # noqa: F401
        import scheduler.jobs.expedition_complete as _expedition_complete_module  # noqa: F401
        import scheduler.jobs.expedition_event as _expedition_event_module  # noqa: F401
        import scheduler.jobs.expedition_resolve as _expedition_resolve_module  # noqa: F401

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

    async def close(self) -> None:
        # Stop notification consumer cleanly.
        consumer = getattr(self, "_notif_consumer", None)
        task = getattr(self, "_notif_task", None)
        if consumer is not None:
            consumer.stop()
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        redis_client = getattr(self, "_notif_redis", None)
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception:
                pass
        await super().close()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Auto-register a Sector row when the bot joins a new guild."""
        async with async_session() as session:
            async with session.begin():
                await register_sector_for_guild(guild, session)
        log.info("registered_sector: guild_id=%s guild_name=%s", guild.id, guild.name)

    async def on_ready(self) -> None:
        log.info("Bot online as %s (ID: %s)", self.user, self.user.id if self.user else "?")
        # Reconcile sectors with current guilds.
        async with async_session() as session:
            async with session.begin():
                await reconcile_sectors_with_guilds(list(self.guilds), session)


async def main() -> None:
    start_http_server(8001)
    log.info("Bot metrics server started on port 8001")
    bot = Dare2DriveBot()
    async with bot:
        await bot.start(settings.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
