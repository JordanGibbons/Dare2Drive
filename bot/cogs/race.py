"""Race cog — /race, /challenge, /leaderboard, /wrecks commands."""

from __future__ import annotations

import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import Build, Card, CardSlot, Race, User, UserCard, WreckLog
from db.session import async_session
from engine.race_engine import RaceResult, compute_race

log = get_logger(__name__)

POSITION_EMOJI = {1: "🥇", 2: "🥈", 3: "🥉"}


async def _resolve_build_for_race(
    session: AsyncSession, user: User
) -> dict[str, Any] | str:
    """
    Load a user's active build and resolve all card data for the race engine.
    Returns the build dict or an error string.
    """
    result = await session.execute(
        select(Build).where(Build.user_id == user.discord_id, Build.is_active == True)
    )
    build = result.scalar_one_or_none()
    if not build:
        return "No active build found."

    # Check all slots for quantity-0 cards
    cards: dict[str, dict[str, Any]] = {}
    for slot in CardSlot:
        card_id = build.slots.get(slot.value)
        if card_id:
            card = await session.get(Card, uuid.UUID(card_id))
            if card:
                # Check ownership
                uc_result = await session.execute(
                    select(UserCard).where(
                        UserCard.user_id == user.discord_id,
                        UserCard.card_id == card.id,
                    )
                )
                uc = uc_result.scalar_one_or_none()
                if uc and uc.quantity <= 0:
                    return f"Your **{slot.value}** slot has a card with quantity 0. Use `/garage` to fix it."
                cards[card_id] = {
                    "id": str(card.id),
                    "name": card.name,
                    "slot": card.slot.value,
                    "rarity": card.rarity.value,
                    "stats": card.stats,
                }

    return {
        "user_id": user.discord_id,
        "slots": build.slots,
        "cards": cards,
    }


async def _apply_wreck_results(session: AsyncSession, race_result: RaceResult, race_id: uuid.UUID) -> None:
    """Apply wreck part losses to the database and create WreckLog entries."""
    for placement in race_result.placements:
        if not placement.wrecked_parts:
            continue

        lost_parts_data = []
        for wp in placement.wrecked_parts:
            # Decrement UserCard quantity
            card_uuid = uuid.UUID(wp.card_id) if wp.card_id else None
            if card_uuid:
                uc_result = await session.execute(
                    select(UserCard).where(
                        UserCard.user_id == placement.user_id,
                        UserCard.card_id == card_uuid,
                    )
                )
                uc = uc_result.scalar_one_or_none()
                if uc:
                    uc.quantity = max(0, uc.quantity - 1)
                    # If quantity 0, unequip from active build
                    if uc.quantity == 0:
                        build_result = await session.execute(
                            select(Build).where(
                                Build.user_id == placement.user_id,
                                Build.is_active == True,
                            )
                        )
                        build = build_result.scalar_one_or_none()
                        if build:
                            new_slots = dict(build.slots)
                            for slot_name, cid in new_slots.items():
                                if cid == wp.card_id:
                                    new_slots[slot_name] = None
                            build.slots = new_slots

            lost_parts_data.append(wp.to_dict())

        # Create WreckLog
        wreck_log = WreckLog(
            race_id=race_id,
            user_id=placement.user_id,
            lost_parts=lost_parts_data,
        )
        session.add(wreck_log)


class RaceCog(commands.Cog):
    """Racing, challenges, and leaderboards."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="race", description="Start a race against another player")
    @app_commands.describe(opponent="The player to race against (omit for random)")
    async def race(self, interaction: discord.Interaction, opponent: discord.Member | None = None) -> None:
        await interaction.response.defer()

        async with async_session() as session:
            # Resolve challenger
            challenger = await session.get(User, str(interaction.user.id))
            if not challenger:
                await interaction.followup.send("Use `/start` first!")
                return

            challenger_build = await _resolve_build_for_race(session, challenger)
            if isinstance(challenger_build, str):
                await interaction.followup.send(challenger_build)
                return

            # Resolve opponent
            if opponent:
                opp_user = await session.get(User, str(opponent.id))
                if not opp_user:
                    await interaction.followup.send(f"{opponent.display_name} hasn't started yet!")
                    return
            else:
                # Random opponent — pick another user
                result = await session.execute(
                    select(User).where(User.discord_id != str(interaction.user.id)).limit(1)
                )
                opp_user = result.scalar_one_or_none()
                if not opp_user:
                    await interaction.followup.send("No opponents available!")
                    return

            opp_build = await _resolve_build_for_race(session, opp_user)
            if isinstance(opp_build, str):
                await interaction.followup.send(f"Opponent error: {opp_build}")
                return

            # Run the race
            race_result = compute_race([challenger_build, opp_build])

            # Store race record
            race_record = Race(
                participants={
                    "players": [challenger.discord_id, opp_user.discord_id],
                },
                environment=race_result.environment.to_dict(),
                results=race_result.to_dict(),
            )
            session.add(race_record)
            await session.flush()

            # Apply wreck results
            await _apply_wreck_results(session, race_result, race_record.id)

            # Award XP
            for placement in race_result.placements:
                user = await session.get(User, placement.user_id)
                if user:
                    if placement.dnf:
                        user.xp += 5
                    elif placement.position == 1:
                        user.xp += 50
                        user.currency += 100
                    elif placement.position == 2:
                        user.xp += 25
                        user.currency += 50
                    else:
                        user.xp += 10

            await session.commit()

        # Build result embeds
        env = race_result.environment
        embed = discord.Embed(
            title=f"🏁 Race — {env.display_name}",
            description=env.description,
            color=0xF59E0B,
        )

        for p in race_result.placements:
            pos_emoji = POSITION_EMOJI.get(p.position, f"P{p.position}")
            status = "💥 DNF" if p.dnf else f"{p.score:.1f} pts"
            embed.add_field(
                name=f"{pos_emoji} <@{p.user_id}>",
                value=f"{status}\n{p.narrative}",
                inline=False,
            )

        if race_result.wrecks:
            wreck_lines = []
            for w in race_result.wrecks:
                parts = ", ".join(p["card_name"] for p in w["lost_parts"])
                wreck_lines.append(f"<@{w['user_id']}> lost: {parts}")
            embed.add_field(name="💥 Wrecks", value="\n".join(wreck_lines), inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="challenge", description="Challenge a specific player to a race")
    @app_commands.describe(opponent="The player to challenge")
    async def challenge(self, interaction: discord.Interaction, opponent: discord.Member) -> None:
        # Delegates to race with explicit opponent
        await self.race.callback(self, interaction, opponent=opponent)

    @app_commands.command(name="leaderboard", description="View the top racers")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            result = await session.execute(
                select(User).order_by(User.xp.desc()).limit(10)
            )
            users = list(result.scalars().all())

        if not users:
            await interaction.response.send_message("No players yet!")
            return

        lines = []
        for i, user in enumerate(users):
            pos = POSITION_EMOJI.get(i + 1, f"**#{i + 1}**")
            lines.append(f"{pos} **{user.username}** — {user.xp} XP, {user.currency} Creds")

        embed = discord.Embed(
            title="🏆 Leaderboard",
            description="\n".join(lines),
            color=0xF59E0B,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="wrecks", description="View your wreck history")
    async def wrecks(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            result = await session.execute(
                select(WreckLog)
                .where(WreckLog.user_id == str(interaction.user.id))
                .order_by(WreckLog.created_at.desc())
                .limit(10)
            )
            logs = list(result.scalars().all())

        if not logs:
            await interaction.response.send_message("No wreck history — keep it clean! 🏁", ephemeral=True)
            return

        lines = []
        for wl in logs:
            parts = ", ".join(p.get("card_name", "?") for p in wl.lost_parts)
            date = wl.created_at.strftime("%Y-%m-%d %H:%M") if wl.created_at else "?"
            lines.append(f"**{date}** — Lost: {parts}")

        embed = discord.Embed(
            title="💥 Wreck History",
            description="\n".join(lines),
            color=0xEF4444,
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RaceCog(bot))
