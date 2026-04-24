"""Admin cog — dev/admin-only commands."""

from __future__ import annotations

from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, func, select, update

from config.logging import get_logger
from config.tracing import traced_command
from db.models import (
    Build,
    MarketListing,
    Sector,
    ShipTitle,
    System,
    TutorialStep,
    User,
    UserCard,
    WreckLog,
)
from db.session import async_session

log = get_logger(__name__)


async def _delete_player_data(session, user_id: str, user: User) -> None:
    """
    Delete all rows owned by *user_id* in the correct FK order, then the user row.

    builds ↔ ship_titles form a circular FK:
      builds.ship_title_id → ship_titles.id
      ship_titles.build_id → builds.id

    Breaking the cycle: NULL out builds.ship_title_id first so ship_titles can
    be deleted, then delete builds, then the user.

    Full order:
      wreck_logs → market_listings → user_cards
      → NULL builds.ship_title_id → ship_titles → builds → user
    """
    await session.execute(delete(WreckLog).where(WreckLog.user_id == user_id))
    await session.execute(delete(MarketListing).where(MarketListing.seller_id == user_id))
    await session.execute(delete(UserCard).where(UserCard.user_id == user_id))
    # Break the circular FK before deleting either side
    await session.execute(update(Build).where(Build.user_id == user_id).values(ship_title_id=None))
    await session.execute(delete(ShipTitle).where(ShipTitle.owner_id == user_id))
    await session.execute(delete(Build).where(Build.user_id == user_id))
    await session.delete(user)


@dataclass
class CommandResult:
    """Lightweight result type returned by testable logic functions."""

    success: bool
    message: str


# ---------------------------------------------------------------------------
# System / Sector logic functions (module-level for testability)
# ---------------------------------------------------------------------------


async def _system_enable_logic(interaction, session) -> CommandResult:
    """Enable the current channel as a system (idempotency-safe)."""
    if not interaction.user.guild_permissions.manage_channels:
        return CommandResult(False, "Only server admins (manage_channels) can enable systems.")

    sys = (
        await session.execute(select(Sector).where(Sector.guild_id == str(interaction.guild_id)))
    ).scalar_one_or_none()
    if sys is None:
        return CommandResult(False, "Sector not registered. Try kicking and re-inviting the bot.")

    enabled_count = (
        await session.execute(
            select(func.count()).select_from(System).where(System.sector_id == sys.guild_id)
        )
    ).scalar_one()
    if enabled_count >= sys.system_cap:
        plural = "s" if sys.system_cap != 1 else ""
        return CommandResult(
            False,
            f"The {sys.name} can only sustain {sys.system_cap} active system{plural} "
            f"at its current influence. Disable another to relocate, or grow "
            f"the sector to expand.",
        )

    existing = (
        await session.execute(
            select(System).where(System.channel_id == str(interaction.channel_id))
        )
    ).scalar_one_or_none()
    if existing is not None:
        return CommandResult(False, "This channel is already an enabled system.")

    sec = System(
        channel_id=str(interaction.channel_id),
        sector_id=sys.guild_id,
        name=interaction.channel.name,
    )
    session.add(sec)
    await session.flush()
    return CommandResult(
        True,
        f"#{sec.name} enabled as a system. "
        f"({enabled_count + 1}/{sys.system_cap} systems active.)",
    )


async def _system_disable_logic(interaction, session) -> CommandResult:
    """Disable the current channel as a system."""
    if not interaction.user.guild_permissions.manage_channels:
        return CommandResult(False, "Only server admins (manage_channels) can disable systems.")

    sec = (
        await session.execute(
            select(System).where(System.channel_id == str(interaction.channel_id))
        )
    ).scalar_one_or_none()
    if sec is None:
        return CommandResult(False, "This channel is not an enabled system.")

    await session.delete(sec)
    await session.flush()
    return CommandResult(True, "System disabled. Gameplay commands will no longer work here.")


async def _system_rename_logic(interaction, new_name: str, session) -> CommandResult:
    """Rename the current channel's system."""
    if not interaction.user.guild_permissions.manage_channels:
        return CommandResult(False, "Only server admins can rename systems.")

    sec = (
        await session.execute(
            select(System).where(System.channel_id == str(interaction.channel_id))
        )
    ).scalar_one_or_none()
    if sec is None:
        return CommandResult(False, "This channel is not an enabled system.")

    sec.name = new_name[:100]
    await session.flush()
    return CommandResult(True, f"System renamed to {sec.name}.")


async def _sector_info_logic(interaction, session) -> CommandResult:
    """Return a formatted summary of this guild's sector."""
    sys = (
        await session.execute(select(Sector).where(Sector.guild_id == str(interaction.guild_id)))
    ).scalar_one_or_none()
    if sys is None:
        return CommandResult(False, "Sector not registered.")

    systems = (
        (await session.execute(select(System).where(System.sector_id == sys.guild_id)))
        .scalars()
        .all()
    )
    system_lines = "\n".join(f"  • #{s.name}" for s in systems) or "  (none enabled)"
    msg = (
        f"**{sys.name}**\n"
        f"{sys.flavor_text or '(no flavor set)'}\n\n"
        f"Capacity: {len(systems)}/{sys.system_cap} systems\n"
        f"Active systems:\n{system_lines}"
    )
    return CommandResult(True, msg)


async def _sector_set_flavor_logic(interaction, flavor: str, session) -> CommandResult:
    """Set the flavor text for the guild's sector (owner-only)."""
    sys = (
        await session.execute(select(Sector).where(Sector.guild_id == str(interaction.guild_id)))
    ).scalar_one_or_none()
    if sys is None:
        return CommandResult(False, "Sector not registered.")
    if str(interaction.user.id) != sys.owner_discord_id:
        return CommandResult(False, "Only the sector owner can set flavor text.")

    sys.flavor_text = flavor[:500]
    await session.flush()
    return CommandResult(True, "Sector flavor updated.")


async def _set_system_cap_logic(interaction, new_cap: int, session) -> CommandResult:
    """Set the system cap for a guild's sector (bot-owner only)."""
    from config.settings import settings

    if str(interaction.user.id) != settings.BOT_OWNER_DISCORD_ID:
        return CommandResult(False, "Unknown command.")  # no info leak

    sys = (
        await session.execute(select(Sector).where(Sector.guild_id == str(interaction.guild_id)))
    ).scalar_one_or_none()
    if sys is None:
        return CommandResult(False, "Sector not registered.")

    sys.system_cap = new_cap
    await session.flush()
    return CommandResult(True, f"System cap for {sys.name} set to {new_cap}.")


def is_admin():
    """Check that the user has administrator permission in the server."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message(
                "Admin commands only work in a server.", ephemeral=True
            )
            return False
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You don't have permission to use admin commands.", ephemeral=True
            )
            return False
        return True

    return app_commands.check(predicate)


class AdminCog(commands.Cog):
    """Admin-only commands for testing and management."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="admin_reset_player",
        description="[ADMIN] Fully wipe a player's account so they can /start again",
    )
    @app_commands.describe(target="The player to reset")
    @is_admin()
    @traced_command
    async def reset_player(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)

        user_id = str(target.id)

        async with async_session() as session:
            user = await session.get(User, user_id)
            if not user:
                await interaction.followup.send(
                    f"{target.display_name} doesn't have an account.", ephemeral=True
                )
                return

            await _delete_player_data(session, user_id, user)
            await session.commit()

        log.info(
            "Admin %s wiped account for %s (%s)", interaction.user.id, target.display_name, user_id
        )
        await interaction.followup.send(
            f"✅ Wiped **{target.display_name}**'s account. They can use `/start` again.",
            ephemeral=True,
        )

    @app_commands.command(
        name="admin_set_tutorial_step",
        description="[ADMIN] Set a player's tutorial step directly",
    )
    @app_commands.describe(
        target="The player to update",
        step="Tutorial step to set",
    )
    @app_commands.choices(
        step=[app_commands.Choice(name=s.value, value=s.value) for s in TutorialStep]
    )
    @is_admin()
    @traced_command
    async def set_tutorial_step(
        self, interaction: discord.Interaction, target: discord.Member, step: str
    ) -> None:

        async with async_session() as session:
            user = await session.get(User, str(target.id))
            if not user:
                await interaction.response.send_message(
                    f"{target.display_name} doesn't have an account.", ephemeral=True
                )
                return

            old_step = user.tutorial_step.value
            user.tutorial_step = TutorialStep(step)
            await session.commit()

        await interaction.response.send_message(
            f"✅ Set **{target.display_name}**'s tutorial step: `{old_step}` → `{step}`",
            ephemeral=True,
        )

    @app_commands.command(
        name="admin_give_creds",
        description="[ADMIN] Add or remove Creds from a player's balance",
    )
    @app_commands.describe(
        target="The player to modify",
        amount="Amount of Creds (positive to add, negative to remove)",
    )
    @is_admin()
    @traced_command
    async def give_creds(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: int,
    ) -> None:
        async with async_session() as session:
            user = await session.get(User, str(target.id))
            if not user:
                await interaction.response.send_message(
                    f"{target.display_name} doesn't have an account.", ephemeral=True
                )
                return

            old_balance = user.currency
            user.currency = max(0, user.currency + amount)
            new_balance = user.currency
            await session.commit()

        action = "Added" if amount >= 0 else "Removed"
        log.info(
            "Admin %s %s %d creds for %s (%s → %s)",
            interaction.user.id,
            action.lower(),
            abs(amount),
            target.display_name,
            old_balance,
            new_balance,
        )
        await interaction.response.send_message(
            f"✅ {action} **{abs(amount)} Creds** for **{target.display_name}** "
            f"({old_balance} → {new_balance})",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # System admin commands
    # ------------------------------------------------------------------

    @app_commands.command(
        name="system_enable",
        description="[ADMIN] Enable this channel as an active game system",
    )
    @traced_command
    async def system_enable(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            async with session.begin():
                result = await _system_enable_logic(interaction, session)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(
        name="system_disable",
        description="[ADMIN] Disable this channel as a game system",
    )
    @traced_command
    async def system_disable(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            async with session.begin():
                result = await _system_disable_logic(interaction, session)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(
        name="system_rename",
        description="[ADMIN] Rename this system",
    )
    @app_commands.describe(new_name="New display name for this system (max 100 chars)")
    @traced_command
    async def system_rename(self, interaction: discord.Interaction, new_name: str) -> None:
        async with async_session() as session:
            async with session.begin():
                result = await _system_rename_logic(interaction, new_name, session)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(
        name="sector_info",
        description="Show this server's sector status and active systems",
    )
    @traced_command
    async def sector_info(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            result = await _sector_info_logic(interaction, session)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(
        name="sector_set_flavor",
        description="[OWNER] Set flavor text for this server's sector",
    )
    @app_commands.describe(flavor="Flavor text (max 500 chars)")
    @traced_command
    async def sector_set_flavor(self, interaction: discord.Interaction, flavor: str) -> None:
        async with async_session() as session:
            async with session.begin():
                result = await _sector_set_flavor_logic(interaction, flavor, session)
        await interaction.response.send_message(result.message, ephemeral=True)

    @app_commands.command(
        name="admin_set_system_cap",
        description="[BOT OWNER] Override system cap for a guild's sector",
    )
    @app_commands.describe(new_cap="New system cap value")
    @traced_command
    async def admin_set_system_cap(self, interaction: discord.Interaction, new_cap: int) -> None:
        async with async_session() as session:
            async with session.begin():
                result = await _set_system_cap_logic(interaction, new_cap, session)
        await interaction.response.send_message(result.message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
