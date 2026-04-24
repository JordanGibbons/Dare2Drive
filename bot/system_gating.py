"""Central registry + helper for system gating of gameplay commands."""

from __future__ import annotations

import discord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import System

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
        # system/sector admin commands
        "system",
        "sector",
    }
)

# Commands that require an enabled system to run.
SYSTEM_GATED_COMMANDS: frozenset[str] = frozenset(
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


def requires_system(command_name: str) -> bool:
    """Return True if a command requires an enabled system to run."""
    return command_name in SYSTEM_GATED_COMMANDS


async def get_active_system(
    interaction: discord.Interaction, session: AsyncSession
) -> System | None:
    """Return the System for this interaction's channel, or None if unregistered/DM."""
    if interaction.guild_id is None:
        return None
    result = await session.execute(
        select(System).where(System.channel_id == str(interaction.channel_id))
    )
    return result.scalar_one_or_none()


def system_required_message() -> str:
    """User-facing message when a gameplay command runs in an unregistered channel."""
    return "Game not enabled here. Ask a server admin to `/system enable` this channel."
