"""Cards cog — /pack, /inventory, /inspect, /daily commands."""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from config.settings import settings
from db.models import Card, Rarity, User, UserCard
from db.session import async_session

log = get_logger(__name__)

_LOOT_TABLES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "loot_tables.json"

RARITY_COLORS = {
    "common": 0x9CA3AF,
    "uncommon": 0x22C55E,
    "rare": 0x3B82F6,
    "epic": 0xA855F7,
    "legendary": 0xF59E0B,
    "ghost": 0xFFFFFF,
}

RARITY_EMOJI = {
    "common": "⬜",
    "uncommon": "🟩",
    "rare": "🟦",
    "epic": "🟪",
    "legendary": "🟨",
    "ghost": "👻",
}


def _load_loot_tables() -> dict[str, Any]:
    with open(_LOOT_TABLES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


async def _roll_cards(session: AsyncSession, pack_type: str, count: int) -> list[Card]:
    """Roll `count` cards from the loot table weighted by rarity."""
    tables = _load_loot_tables()
    table = tables[pack_type]
    weights = table["weights"]

    rarities = list(weights.keys())
    rarity_weights = [weights[r] for r in rarities]

    rolled_cards: list[Card] = []
    for _ in range(count):
        chosen_rarity = random.choices(rarities, weights=rarity_weights, k=1)[0]
        result = await session.execute(
            select(Card).where(Card.rarity == chosen_rarity)
        )
        pool = list(result.scalars().all())
        if pool:
            rolled_cards.append(random.choice(pool))
    return rolled_cards


async def _grant_card(session: AsyncSession, user_id: str, card: Card) -> UserCard:
    """Give a card to a user — increment quantity if they already own it."""
    result = await session.execute(
        select(UserCard).where(UserCard.user_id == user_id, UserCard.card_id == card.id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.quantity += 1
        await session.flush()
        return existing
    else:
        uc = UserCard(user_id=user_id, card_id=card.id, quantity=1)
        session.add(uc)
        await session.flush()
        return uc


class CardsCog(commands.Cog):
    """Card pack opening, inventory, and inspection."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="daily", description="Claim your daily Creds and a chance at a card")
    async def daily(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message(
                    "You haven't started yet! Use `/start` first.", ephemeral=True
                )
                return

            amount = random.randint(settings.DAILY_MIN, settings.DAILY_MAX)
            user.currency += amount

            # 20% chance for a free common card
            bonus_card = None
            if random.random() < 0.2:
                result = await session.execute(
                    select(Card).where(Card.rarity == Rarity.COMMON)
                )
                commons = list(result.scalars().all())
                if commons:
                    bonus_card = random.choice(commons)
                    await _grant_card(session, user.discord_id, bonus_card)

            await session.commit()

        embed = discord.Embed(
            title="💰 Daily Reward",
            description=f"You earned **{amount} Creds**!",
            color=0x22C55E,
        )
        embed.add_field(name="New Balance", value=f"{user.currency} Creds")
        if bonus_card:
            embed.add_field(
                name="Bonus Card!",
                value=f"{RARITY_EMOJI.get(bonus_card.rarity.value, '')} **{bonus_card.name}** ({bonus_card.rarity.value})",
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pack", description="Open a card pack")
    @app_commands.describe(pack_type="Pack type: junkyard_pack, performance_pack, or legend_crate")
    @app_commands.choices(pack_type=[
        app_commands.Choice(name="Junkyard Pack (100 Creds)", value="junkyard_pack"),
        app_commands.Choice(name="Performance Pack (350 Creds)", value="performance_pack"),
        app_commands.Choice(name="Legend Crate (1200 Creds)", value="legend_crate"),
    ])
    async def pack(self, interaction: discord.Interaction, pack_type: str) -> None:
        cost_map = {
            "junkyard_pack": settings.JUNKYARD_PACK_COST,
            "performance_pack": settings.PERFORMANCE_PACK_COST,
            "legend_crate": settings.LEGEND_CRATE_COST,
        }
        cost = cost_map.get(pack_type)
        if cost is None:
            await interaction.response.send_message("Invalid pack type.", ephemeral=True)
            return

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message(
                    "Use `/start` first!", ephemeral=True
                )
                return
            if user.currency < cost:
                await interaction.response.send_message(
                    f"Not enough Creds! You need {cost} but have {user.currency}.",
                    ephemeral=True,
                )
                return

            user.currency -= cost
            cards = await _roll_cards(session, pack_type, 3)

            for card in cards:
                await _grant_card(session, user.discord_id, card)

            await session.commit()

        # Staged reveal — send initial embed then follow up per card
        tables = _load_loot_tables()
        display_name = tables[pack_type]["display_name"]
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"🎴 Opening {display_name}...",
                description="Cards incoming...",
                color=0xF59E0B,
            )
        )

        for i, card in enumerate(cards):
            await asyncio.sleep(0.8)
            color = RARITY_COLORS.get(card.rarity.value, 0x9CA3AF)
            emoji = RARITY_EMOJI.get(card.rarity.value, "")
            embed = discord.Embed(
                title=f"{emoji} {card.name}",
                description=f"**Slot:** {card.slot.value.title()}\n**Rarity:** {card.rarity.value.title()}",
                color=color,
            )
            # Show primary stats
            primary = card.stats.get("primary", {})
            stat_lines = [f"`{k}`: {v}" for k, v in primary.items()]
            if stat_lines:
                embed.add_field(name="Primary Stats", value="\n".join(stat_lines), inline=True)
            secondary = card.stats.get("secondary", {})
            sec_lines = [f"`{k}`: {v}" for k, v in secondary.items()]
            if sec_lines:
                embed.add_field(name="Secondary Stats", value="\n".join(sec_lines), inline=True)
            if card.print_max:
                embed.set_footer(text=f"Limited Edition — {card.print_max} prints")
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="inventory", description="View your card collection")
    @app_commands.describe(page="Page number (10 cards per page)")
    async def inventory(self, interaction: discord.Interaction, page: int = 1) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            result = await session.execute(
                select(UserCard).where(UserCard.user_id == user.discord_id)
            )
            user_cards = list(result.scalars().all())

        if not user_cards:
            await interaction.response.send_message("Your inventory is empty! Try `/pack`.", ephemeral=True)
            return

        per_page = 10
        total_pages = max(1, (len(user_cards) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        page_cards = user_cards[start : start + per_page]

        lines = []
        for uc in page_cards:
            card = uc.card
            emoji = RARITY_EMOJI.get(card.rarity.value, "")
            qty_str = f"x{uc.quantity}" if uc.quantity != 1 else ""
            foil = "✨ " if uc.is_foil else ""
            lines.append(f"{emoji} **{card.name}** [{card.slot.value}] {foil}{qty_str}")

        embed = discord.Embed(
            title=f"🗃️ {interaction.user.display_name}'s Inventory",
            description="\n".join(lines),
            color=0x3B82F6,
        )
        embed.set_footer(text=f"Page {page}/{total_pages} • {len(user_cards)} cards total")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="inspect", description="Inspect a card's full stats")
    @app_commands.describe(card_name="Name of the card to inspect")
    async def inspect(self, interaction: discord.Interaction, card_name: str) -> None:
        async with async_session() as session:
            result = await session.execute(select(Card).where(Card.name == card_name))
            card = result.scalar_one_or_none()

        if not card:
            await interaction.response.send_message(
                f"Card `{card_name}` not found.", ephemeral=True
            )
            return

        color = RARITY_COLORS.get(card.rarity.value, 0x9CA3AF)
        emoji = RARITY_EMOJI.get(card.rarity.value, "")
        embed = discord.Embed(
            title=f"{emoji} {card.name}",
            color=color,
        )
        embed.add_field(name="Slot", value=card.slot.value.title(), inline=True)
        embed.add_field(name="Rarity", value=card.rarity.value.title(), inline=True)
        if card.print_max:
            embed.add_field(name="Print Run", value=f"Limited to {card.print_max}", inline=True)

        primary = card.stats.get("primary", {})
        if primary:
            bars = []
            for stat, val in primary.items():
                filled = int(val / 100 * 10) if isinstance(val, (int, float)) else 0
                filled = max(0, min(10, filled))
                bar = "█" * filled + "░" * (10 - filled)
                bars.append(f"`{stat:>25s}` {bar} {val}")
            embed.add_field(name="Primary Stats", value="\n".join(bars), inline=False)

        secondary = card.stats.get("secondary", {})
        if secondary:
            bars = []
            for stat, val in secondary.items():
                if isinstance(val, float) and val < 2:
                    bars.append(f"`{stat:>25s}` {val}")
                else:
                    filled = int(abs(val) / 100 * 10) if isinstance(val, (int, float)) else 0
                    filled = max(0, min(10, filled))
                    bar = "█" * filled + "░" * (10 - filled)
                    bars.append(f"`{stat:>25s}` {bar} {val}")
            embed.add_field(name="Secondary Stats", value="\n".join(bars), inline=False)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CardsCog(bot))
