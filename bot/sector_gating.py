"""Central registry + helper for sector gating of gameplay commands."""

from __future__ import annotations

import discord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Sector

# Commands that work anywhere (DMs, any channel, registered or not).
UNIVERSE_WIDE_COMMANDS: frozenset[str] = frozenset(
    {
        "profile",
        "inventory",
        "inspect",
        "help",
        "start",
        "skip_tutorial",
        "garage",  # legacy alias retained during transition
        "hangar",
        # admin
        "admin_reset_player",
        "admin_set_tutorial_step",
        "admin_give_creds",
        # sector/system admin commands
        "sector",
        "system",
    }
)

# Commands that require an enabled sector to run.
SECTOR_GATED_COMMANDS: frozenset[str] = frozenset(
    {
        "race",
        "challenge",
        "pack",
        "daily",
        "equip",
        "autoequip",
        "preview",
        "mint",
        "leaderboard",
        "wrecks",
        "market",
        "list",
        "buy",
    }
)


def requires_sector(command_name: str) -> bool:
    """Return True if a command requires an enabled sector to run."""
    return command_name in SECTOR_GATED_COMMANDS


async def get_active_sector(
    interaction: discord.Interaction, session: AsyncSession
) -> Sector | None:
    """Return the Sector for this interaction's channel, or None if unregistered/DM."""
    if interaction.guild_id is None:
        return None
    result = await session.execute(
        select(Sector).where(Sector.channel_id == str(interaction.channel_id))
    )
    return result.scalar_one_or_none()


def sector_required_message() -> str:
    """User-facing message when a gameplay command runs in an unregistered channel."""
    return "Game not enabled here. Ask a server admin to `/sector enable` this channel."
