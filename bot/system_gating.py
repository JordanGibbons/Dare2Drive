"""Central registry + helper for system gating of gameplay commands."""

from __future__ import annotations

import discord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import System

# Commands that work anywhere (DMs, any channel, registered or not).
#
# Ship/build ownership is universe-wide: a player can inspect their cards and
# manage their builds from any channel the bot is in. Competitive and economic
# activity is sector-scoped — see SYSTEM_GATED_COMMANDS below.
UNIVERSE_WIDE_COMMANDS: frozenset[str] = frozenset(
    {
        # Account + read-only
        "profile",
        "inventory",
        "inspect",
        "help",
        "start",
        "skip_tutorial",
        "garage",  # legacy alias retained during transition
        "hangar",
        "peek",
        "request_inspect",
        # Build / ship management (personal, not sector-bound)
        "equip",
        "autoequip",
        "preview",
        "mint",
        # Admin
        "admin_reset_player",
        "admin_set_tutorial_step",
        "admin_give_creds",
        # System/sector admin commands
        "system",
        "sector",
    }
)

# Commands that require an enabled system to run.
#
# Policy: ship/build ownership is universe-wide (a player can view and manage
# their builds anywhere the bot is enabled). Gameplay activity — racing,
# economy, sector-scoped state — requires an active system in the channel.
# Future phases may attach ship location to a specific system; that change
# would make ship movement/arrival commands gated as well.
SYSTEM_GATED_COMMANDS: frozenset[str] = frozenset(
    {
        # Racing & competition
        "race",
        "multirace",
        "leaderboard",
        "wrecks",
        # Economy — pack/daily rewards and marketplace activity
        "pack",
        "daily",
        "market",
        "list",
        "buy",
        "trade",
        "shop",
        "shop_buy",
        "salvage",
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
