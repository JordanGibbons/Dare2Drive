"""Cards cog — /pack, /inventory, /inspect, /daily commands."""

from __future__ import annotations

import io
import json
import random
import re
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.metrics import currency_spent, daily_claimed, packs_opened
from config.logging import get_logger
from config.metrics import trace_exemplar
from config.settings import settings
from db.models import Build, Card, CardSlot, Rarity, User, UserCard
from db.session import async_session

_SALVAGE_RATES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "salvage_rates.json"

_salvage_rates_cache: dict[str, int] | None = None


def _get_salvage_rates() -> dict[str, int]:
    global _salvage_rates_cache
    if _salvage_rates_cache is None:
        with open(_SALVAGE_RATES_PATH, "r", encoding="utf-8") as f:
            _salvage_rates_cache = json.load(f)
    return _salvage_rates_cache


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


_SERIAL_SUFFIX_RE = re.compile(r"^(.+?)\s*#(\d+)$")


def _parse_card_input(card_name: str) -> tuple[str, int | None]:
    """
    Parse a card_name string that may include a serial suffix.

    "Rustbucket Inline-4 #3" → ("Rustbucket Inline-4", 3)
    "Rustbucket Inline-4"    → ("Rustbucket Inline-4", None)
    """
    m = _SERIAL_SUFFIX_RE.match(card_name.strip())
    if m:
        return m.group(1).strip(), int(m.group(2))
    return card_name.strip(), None


async def _card_copy_autocomplete(
    interaction: discord.Interaction,
    current: str,
    slot_filter: str | None = None,
) -> list[app_commands.Choice[str]]:
    """
    Autocomplete showing individual card copies as 'Card Name #serial'.
    If the user owns only one copy of a card, just shows 'Card Name'.
    """
    # Strip any #serial from what the user has typed so far
    search_text, _ = _parse_card_input(current)

    async with async_session() as session:
        query = (
            select(Card.name, UserCard.serial_number)
            .join(UserCard, UserCard.card_id == Card.id)
            .where(
                UserCard.user_id == str(interaction.user.id),
                Card.name.ilike(f"%{search_text}%"),
            )
            .order_by(Card.name, UserCard.serial_number)
            .limit(25)
        )
        if slot_filter:
            query = query.where(Card.slot == slot_filter)

        result = await session.execute(query)
        rows = result.all()

    # Count copies per card name to decide display format
    from collections import Counter

    name_counts = Counter(name for name, _ in rows)

    choices = []
    for name, serial in rows:
        if name_counts[name] > 1:
            label = f"{name} #{serial}"
        else:
            label = name
        choices.append(app_commands.Choice(name=label, value=label))
    return choices


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
        result = await session.execute(select(Card).where(Card.rarity == chosen_rarity))
        pool = list(result.scalars().all())
        if pool:
            rolled_cards.append(random.choice(pool))
    return rolled_cards


async def _grant_card(session: AsyncSession, user_id: str, card: Card) -> UserCard:
    """Mint a new individual copy of a card for a user."""
    from engine.card_mint import mint_card

    return await mint_card(session, user_id, card)


class CardsCog(commands.Cog):
    """Card pack opening, inventory, and inspection."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="daily", description="Claim your daily Creds and a full set of parts"
    )
    async def daily(self, interaction: discord.Interaction) -> None:
        from datetime import datetime, timedelta, timezone

        # Rarity weights for daily parts: common is most likely, ghost is ultra rare
        DAILY_RARITY_WEIGHTS = {
            "common": 50,
            "uncommon": 25,
            "rare": 15,
            "epic": 7,
            "legendary": 2.5,
            "ghost": 0.5,
        }
        DAILY_SLOTS = [
            "engine",
            "transmission",
            "tires",
            "chassis",
            "brakes",
            "suspension",
            "turbo",
        ]

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message(
                    "You haven't started yet! Use `/start` first.", ephemeral=True
                )
                return

            now = datetime.now(timezone.utc)
            if user.last_daily:
                next_daily = user.last_daily + timedelta(hours=24)
                if now < next_daily:
                    remaining = next_daily - now
                    hours, rem = divmod(int(remaining.total_seconds()), 3600)
                    minutes = rem // 60
                    await interaction.response.send_message(
                        f"You already claimed your daily! Come back in **{hours}h {minutes}m**.",
                        ephemeral=True,
                    )
                    return

            user.currency += 100
            user.last_daily = now

            # Roll a part for each slot with rarity-scaled probability
            rarities = list(DAILY_RARITY_WEIGHTS.keys())
            weights = [DAILY_RARITY_WEIGHTS[r] for r in rarities]

            granted_parts: list[tuple[Card, UserCard]] = []
            for slot in DAILY_SLOTS:
                chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]
                result = await session.execute(
                    select(Card).where(Card.slot == slot, Card.rarity == chosen_rarity)
                )
                pool = list(result.scalars().all())
                if not pool:
                    # Fallback to common if no cards exist for this rarity+slot
                    result = await session.execute(
                        select(Card).where(Card.slot == slot, Card.rarity == "common")
                    )
                    pool = list(result.scalars().all())
                if pool:
                    card = random.choice(pool)
                    uc = await _grant_card(session, user.discord_id, card)
                    granted_parts.append((card, uc))

            await session.commit()

        daily_claimed.inc(exemplar=trace_exemplar())

        embed = discord.Embed(
            title="💰 Daily Reward",
            description="You earned **100 Creds** and a full set of parts!",
            color=0x22C55E,
        )
        embed.add_field(name="New Balance", value=f"{user.currency} Creds", inline=False)

        if granted_parts:
            part_lines = []
            for card, uc in granted_parts:
                emoji = RARITY_EMOJI.get(card.rarity.value, "")
                part_lines.append(
                    f"{emoji} **{card.name}** #{uc.serial_number} [{card.slot.value}]"
                )
            embed.add_field(name="Today's Parts", value="\n".join(part_lines), inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pack", description="Open a card pack")
    @app_commands.describe(pack_type="Pack type: junkyard_pack, performance_pack, or legend_crate")
    @app_commands.choices(
        pack_type=[
            app_commands.Choice(name="Junkyard Pack (100 Creds)", value="junkyard_pack"),
            app_commands.Choice(name="Performance Pack (350 Creds)", value="performance_pack"),
            app_commands.Choice(name="Legend Crate (1200 Creds)", value="legend_crate"),
        ]
    )
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
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return
            if user.currency < cost:
                await interaction.response.send_message(
                    f"Not enough Creds! You need {cost} but have {user.currency}.",
                    ephemeral=True,
                )
                return

            user.currency -= cost
            cards = await _roll_cards(session, pack_type, 3)

            minted: list[tuple[Card, UserCard]] = []
            for card in cards:
                uc = await _grant_card(session, user.discord_id, card)
                minted.append((card, uc))

            await session.commit()

        packs_opened.labels(pack_type=pack_type).inc(exemplar=trace_exemplar())
        currency_spent.labels(reason=pack_type).inc(cost, exemplar=trace_exemplar())

        tables = _load_loot_tables()
        display_name = tables[pack_type]["display_name"]
        view = _PackRevealView(
            minted=minted, display_name=display_name, owner_id=interaction.user.id
        )
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @app_commands.command(name="inventory", description="View your card collection")
    async def inventory(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            result = await session.execute(
                select(UserCard)
                .where(UserCard.user_id == user.discord_id)
                .options(selectinload(UserCard.card))
            )
            user_cards = list(result.scalars().all())

        if not user_cards:
            await interaction.response.send_message(
                "Your inventory is empty! Try `/pack`.", ephemeral=True
            )
            return

        # Auto sort: by slot type, then rarity (best first), then serial
        slot_order = {s.value: i for i, s in enumerate(CardSlot)}
        rarity_order = {
            "ghost": 0,
            "legendary": 1,
            "epic": 2,
            "rare": 3,
            "uncommon": 4,
            "common": 5,
        }
        user_cards.sort(
            key=lambda uc: (
                slot_order.get(uc.card.slot.value, 99),
                rarity_order.get(uc.card.rarity.value, 99),
                uc.serial_number,
            )
        )

        view = _InventoryView(
            user_cards=user_cards,
            owner_id=interaction.user.id,
            owner_name=interaction.user.display_name,
        )
        embed = view.build_page_embed()
        await interaction.response.send_message(embed=embed, view=view)

        # Tutorial progression
        from bot.cogs.tutorial import advance_tutorial

        await advance_tutorial(interaction, str(interaction.user.id), "inventory")

    @app_commands.command(name="inspect", description="Inspect a card's full stats")
    @app_commands.describe(card_name="Name of the card to inspect (e.g. Card Name #3)")
    async def inspect(self, interaction: discord.Interaction, card_name: str) -> None:
        from engine.card_mint import apply_stat_modifiers

        parsed_name, parsed_serial = _parse_card_input(card_name)

        async with async_session() as session:
            result = await session.execute(select(Card).where(Card.name == parsed_name))
            card = result.scalar_one_or_none()

            if not card:
                await interaction.response.send_message(
                    f"Card `{parsed_name}` not found.", ephemeral=True
                )
                return

            # Find the specific copy (by serial if given, else lowest serial)
            query = select(UserCard).where(
                UserCard.user_id == str(interaction.user.id),
                UserCard.card_id == card.id,
            )
            if parsed_serial is not None:
                query = query.where(UserCard.serial_number == parsed_serial)
            else:
                query = query.order_by(UserCard.serial_number)
            query = query.limit(1)

            uc_result = await session.execute(query)
            user_copy = uc_result.scalar_one_or_none()

        if not user_copy:
            await interaction.response.send_message(f"You don't own `{card_name}`.", ephemeral=True)
            return

        # Apply per-copy stat modifiers
        effective_stats = apply_stat_modifiers(card.stats, user_copy.stat_modifiers or {})

        color = RARITY_COLORS.get(card.rarity.value, 0x9CA3AF)
        emoji = RARITY_EMOJI.get(card.rarity.value, "")
        embed = discord.Embed(
            title=f"{emoji} {card.name} #{user_copy.serial_number}",
            color=color,
        )
        embed.add_field(name="Slot", value=card.slot.value.title(), inline=True)
        embed.add_field(name="Rarity", value=card.rarity.value.title(), inline=True)
        embed.add_field(
            name="Print",
            value=f"#{user_copy.serial_number} of {card.total_minted}",
            inline=True,
        )

        # Wear indicator
        from bot.cogs.race import get_part_lifespan

        lifespan = get_part_lifespan(card.slot.value, card.rarity.value)
        races_left = max(0, lifespan - user_copy.races_used)
        if races_left <= 3:
            wear_str = f"⚠️ {races_left}/{lifespan} races left"
        else:
            wear_str = f"{races_left}/{lifespan} races left"
        embed.add_field(name="Wear", value=wear_str, inline=True)

        # Show stat deltas only if degradation has occurred
        all_base = {**card.stats.get("primary", {}), **card.stats.get("secondary", {})}
        all_eff = {**effective_stats.get("primary", {}), **effective_stats.get("secondary", {})}
        delta_lines = []
        for stat, base in all_base.items():
            if not isinstance(base, (int, float)):
                continue
            eff = all_eff.get(stat, base)
            if isinstance(eff, (int, float)) and abs(eff - base) > 0.01:
                delta_lines.append(f"`{stat}` {eff:.1f} ({eff - base:+.1f})")
        if delta_lines:
            embed.add_field(name="Degraded Stats", value="\n".join(delta_lines), inline=False)

        if user_copy.is_foil:
            embed.set_footer(text="✨ Foil Edition")

        # Render card image and attach it
        from scripts.generate_card_image import render_card

        card_data = {
            "name": card.name,
            "slot": card.slot.value,
            "rarity": card.rarity.value,
            "stats": effective_stats,
            "print_max": card.print_max,
        }
        img = render_card(card_data, print_number=user_copy.serial_number)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        file = discord.File(buf, filename="card.png")
        embed.set_image(url="attachment://card.png")

        await interaction.response.send_message(embed=embed, file=file)

        # Tutorial progression
        from bot.cogs.tutorial import advance_tutorial

        await advance_tutorial(interaction, str(interaction.user.id), "inspect")

    @inspect.autocomplete("card_name")
    async def inspect_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await _card_copy_autocomplete(interaction, current)

    @app_commands.command(
        name="request_inspect", description="Ask to peek inside another player's garage"
    )
    @app_commands.describe(target="The player whose garage you want to see")
    async def request_inspect(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
    ) -> None:
        if target.id == interaction.user.id:
            await interaction.response.send_message(
                "Just use `/inventory` for your own cards.", ephemeral=True
            )
            return

        if target.bot:
            await interaction.response.send_message("Bots don't have garages.", ephemeral=True)
            return

        async with async_session() as session:
            target_user = await session.get(User, str(target.id))
            if not target_user:
                await interaction.response.send_message(
                    f"{target.display_name} hasn't started playing yet.", ephemeral=True
                )
                return

        view = _GarageRequestView(
            requester_id=interaction.user.id,
            target_id=target.id,
            target_name=target.display_name,
        )
        embed = discord.Embed(
            title="🔍 Garage Access Request",
            description=(
                f"{interaction.user.mention} is knocking on your garage door.\n"
                f"They want to take a look at what you're working with.\n\n"
                f"{target.mention}, let them in?"
            ),
            color=0xF59E0B,
        )
        await interaction.response.send_message(embed=embed, view=view)


SLOT_ORDER = {s.value: i for i, s in enumerate(CardSlot)}
RARITY_ORDER_DESC = {"ghost": 0, "legendary": 1, "epic": 2, "rare": 3, "uncommon": 4, "common": 5}


class _PackRevealView(discord.ui.View):
    """Single-message pack reveal widget — scroll through cards one at a time."""

    def __init__(
        self,
        minted: list[tuple],
        display_name: str,
        owner_id: int,
    ) -> None:
        super().__init__(timeout=120)
        self.minted = minted
        self.display_name = display_name
        self.owner_id = owner_id
        self.index = 0
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_card.disabled = self.index == 0
        self.next_card.disabled = self.index == len(self.minted) - 1

    def build_embed(self) -> discord.Embed:
        card, uc = self.minted[self.index]
        color = RARITY_COLORS.get(card.rarity.value, 0x9CA3AF)
        emoji = RARITY_EMOJI.get(card.rarity.value, "")
        embed = discord.Embed(
            title=f"{emoji} {card.name} #{uc.serial_number}",
            description=(
                f"**Slot:** {card.slot.value.title()}\n**Rarity:** {card.rarity.value.title()}"
            ),
            color=color,
        )
        primary = card.stats.get("primary", {})
        if primary:
            embed.add_field(
                name="Primary Stats",
                value="\n".join(f"`{k}`: {v}" for k, v in primary.items()),
                inline=True,
            )
        secondary = card.stats.get("secondary", {})
        if secondary:
            embed.add_field(
                name="Secondary Stats",
                value="\n".join(f"`{k}`: {v}" for k, v in secondary.items()),
                inline=True,
            )
        if card.print_max:
            footer = f"Limited Edition — {card.print_max} prints"
        else:
            footer = ""
        card_counter = f"Card {self.index + 1} of {len(self.minted)} • {self.display_name}"
        embed.set_footer(text=f"{footer}  {card_counter}".strip(" •"))
        return embed

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_card(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't your pack.", ephemeral=True)
            return
        self.index -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_card(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't your pack.", ephemeral=True)
            return
        self.index += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self) -> None:
        self.stop()


class _InventoryView(discord.ui.View):
    """Interactive paginated inventory with a select dropdown to inspect parts."""

    PER_PAGE = 10

    def __init__(self, user_cards: list, owner_id: int, owner_name: str) -> None:
        super().__init__(timeout=300)
        self.user_cards = user_cards
        self.owner_id = owner_id
        self.owner_name = owner_name
        self.page = 1
        self.total_pages = max(1, (len(user_cards) + self.PER_PAGE - 1) // self.PER_PAGE)
        self._card_map = {str(uc.id): uc for uc in user_cards}
        self._rebuild_select()

    def _page_cards(self) -> list:
        start = (self.page - 1) * self.PER_PAGE
        return self.user_cards[start : start + self.PER_PAGE]

    def _rebuild_select(self) -> None:
        """Rebuild the select dropdown for the current page."""
        # Remove old select if it exists
        for item in list(self.children):
            if isinstance(item, discord.ui.Select):
                self.remove_item(item)

        page_cards = self._page_cards()
        if not page_cards:
            return

        options = []
        for uc in page_cards:
            card = uc.card
            emoji = RARITY_EMOJI.get(card.rarity.value, "")
            foil = " ✨" if uc.is_foil else ""
            options.append(
                discord.SelectOption(
                    label=f"{card.name} #{uc.serial_number}"[:100],
                    description=f"{card.slot.value.title()} • {card.rarity.value.title()}{foil}"[
                        :100
                    ],
                    value=str(uc.id),
                    emoji=emoji or None,
                )
            )

        self.card_select = discord.ui.Select(
            placeholder="Select a part to inspect...",
            options=options,
            row=0,
        )
        self.card_select.callback = self._on_select
        self.add_item(self.card_select)

    def build_page_embed(self) -> discord.Embed:
        page_cards = self._page_cards()
        lines = []
        for uc in page_cards:
            card = uc.card
            emoji = RARITY_EMOJI.get(card.rarity.value, "")
            foil = " ✨" if uc.is_foil else ""
            lines.append(f"{emoji} **{card.name}** #{uc.serial_number} [{card.slot.value}]{foil}")

        embed = discord.Embed(
            title=f"🗃️ {self.owner_name}'s Inventory",
            description="\n".join(lines) if lines else "Empty page.",
            color=0x3B82F6,
        )
        embed.set_footer(
            text=f"Page {self.page}/{self.total_pages} • {len(self.user_cards)} cards total"
        )
        return embed

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't your inventory.", ephemeral=True)
            return

        uc = self._card_map.get(self.card_select.values[0])
        if not uc:
            await interaction.response.send_message("Card not found.", ephemeral=True)
            return

        from engine.card_mint import apply_stat_modifiers

        card = uc.card
        effective_stats = apply_stat_modifiers(card.stats, uc.stat_modifiers or {})

        color = RARITY_COLORS.get(card.rarity.value, 0x9CA3AF)
        r_emoji = RARITY_EMOJI.get(card.rarity.value, "")
        embed = discord.Embed(
            title=f"{r_emoji} {card.name} #{uc.serial_number}",
            color=color,
        )
        embed.add_field(name="Slot", value=card.slot.value.title(), inline=True)
        embed.add_field(name="Rarity", value=card.rarity.value.title(), inline=True)
        embed.add_field(
            name="Serial", value=f"#{uc.serial_number} of {card.total_minted}", inline=True
        )

        primary = effective_stats.get("primary", {})
        if primary:
            base_primary = card.stats.get("primary", {})
            bars = []
            for stat, val in primary.items():
                base = base_primary.get(stat, val)
                filled = int(abs(val) / 100 * 10) if isinstance(val, (int, float)) else 0
                filled = max(0, min(10, filled))
                bar = "█" * filled + "░" * (10 - filled)
                delta = (
                    val - base
                    if isinstance(val, (int, float)) and isinstance(base, (int, float))
                    else 0
                )
                delta_str = f" ({delta:+.1f})" if abs(delta) > 0.01 else ""
                bars.append(f"`{stat:>25s}` {bar} {val:.1f}{delta_str}")
            embed.add_field(name="Primary Stats", value="\n".join(bars), inline=False)

        secondary = effective_stats.get("secondary", {})
        if secondary:
            base_secondary = card.stats.get("secondary", {})
            bars = []
            for stat, val in secondary.items():
                base = base_secondary.get(stat, val)
                delta = (
                    val - base
                    if isinstance(val, (int, float)) and isinstance(base, (int, float))
                    else 0
                )
                delta_str = f" ({delta:+.1f})" if abs(delta) > 0.01 else ""
                if isinstance(val, float) and abs(val) < 2:
                    bars.append(f"`{stat:>25s}` {val:.2f}{delta_str}")
                else:
                    filled = int(abs(val) / 100 * 10) if isinstance(val, (int, float)) else 0
                    filled = max(0, min(10, filled))
                    bar = "█" * filled + "░" * (10 - filled)
                    bars.append(f"`{stat:>25s}` {bar} {val:.1f}{delta_str}")
            embed.add_field(name="Secondary Stats", value="\n".join(bars), inline=False)

        if uc.is_foil:
            embed.set_footer(text="✨ Foil Edition")

        detail_view = _InventoryDetailView(self)
        await interaction.response.edit_message(embed=embed, view=detail_view)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't your inventory.", ephemeral=True)
            return
        if self.page > 1:
            self.page -= 1
            self._rebuild_select()
        await interaction.response.edit_message(embed=self.build_page_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't your inventory.", ephemeral=True)
            return
        if self.page < self.total_pages:
            self.page += 1
            self._rebuild_select()
        await interaction.response.edit_message(embed=self.build_page_embed(), view=self)

    async def on_timeout(self) -> None:
        self.stop()


class _InventoryDetailView(discord.ui.View):
    """Back button from inventory detail to inventory list."""

    def __init__(self, inv_view: _InventoryView) -> None:
        super().__init__(timeout=300)
        self.inv_view = inv_view

    @discord.ui.button(label="Back to Inventory", style=discord.ButtonStyle.primary, emoji="🔙")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.inv_view.owner_id:
            await interaction.response.send_message("This isn't your inventory.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=self.inv_view.build_page_embed(), view=self.inv_view
        )


def _build_inventory_embed(
    target_name: str, requester_id: int, user_cards: list, flavor: str
) -> discord.Embed:
    """Build the garage inventory list embed."""
    lines = []
    for uc in user_cards:
        card = uc.card
        emoji = RARITY_EMOJI.get(card.rarity.value, "")
        foil = " ✨" if uc.is_foil else ""
        lines.append(f"{emoji} **{card.name}** #{uc.serial_number} [{card.slot.value}]{foil}")

    description = f"*{flavor}*\n\n<@{requester_id}>, here's what's in the garage:\n\n"
    description += "\n".join(lines[:30])
    if len(lines) > 30:
        description += f"\n\n*...and {len(lines) - 30} more parts.*"

    embed = discord.Embed(
        title=f"🔍 {target_name}'s Garage",
        description=description,
        color=0x3B82F6,
    )
    embed.set_footer(text=f"{len(user_cards)} parts total • Select a part below to inspect it")
    return embed


def _build_card_detail_embed(card: Card, uc: UserCard, target_name: str) -> discord.Embed:
    """Build a full stat inspect embed for a card copy."""
    from engine.card_mint import apply_stat_modifiers

    effective_stats = apply_stat_modifiers(card.stats, uc.stat_modifiers or {})

    color = RARITY_COLORS.get(card.rarity.value, 0x9CA3AF)
    emoji = RARITY_EMOJI.get(card.rarity.value, "")
    embed = discord.Embed(
        title=f"{emoji} {card.name} #{uc.serial_number}",
        description=f"From **{target_name}**'s garage",
        color=color,
    )
    embed.add_field(name="Slot", value=card.slot.value.title(), inline=True)
    embed.add_field(name="Rarity", value=card.rarity.value.title(), inline=True)
    embed.add_field(name="Serial", value=f"#{uc.serial_number} of {card.total_minted}", inline=True)

    primary = effective_stats.get("primary", {})
    if primary:
        base_primary = card.stats.get("primary", {})
        bars = []
        for stat, val in primary.items():
            base = base_primary.get(stat, val)
            filled = int(abs(val) / 100 * 10) if isinstance(val, (int, float)) else 0
            filled = max(0, min(10, filled))
            bar = "█" * filled + "░" * (10 - filled)
            delta = (
                val - base
                if isinstance(val, (int, float)) and isinstance(base, (int, float))
                else 0
            )
            delta_str = f" ({delta:+.1f})" if abs(delta) > 0.01 else ""
            bars.append(f"`{stat:>25s}` {bar} {val:.1f}{delta_str}")
        embed.add_field(name="Primary Stats", value="\n".join(bars), inline=False)

    secondary = effective_stats.get("secondary", {})
    if secondary:
        base_secondary = card.stats.get("secondary", {})
        bars = []
        for stat, val in secondary.items():
            base = base_secondary.get(stat, val)
            delta = (
                val - base
                if isinstance(val, (int, float)) and isinstance(base, (int, float))
                else 0
            )
            delta_str = f" ({delta:+.1f})" if abs(delta) > 0.01 else ""
            if isinstance(val, float) and abs(val) < 2:
                bars.append(f"`{stat:>25s}` {val:.2f}{delta_str}")
            else:
                filled = int(abs(val) / 100 * 10) if isinstance(val, (int, float)) else 0
                filled = max(0, min(10, filled))
                bar = "█" * filled + "░" * (10 - filled)
                bars.append(f"`{stat:>25s}` {bar} {val:.1f}{delta_str}")
        embed.add_field(name="Secondary Stats", value="\n".join(bars), inline=False)

    if uc.is_foil:
        embed.set_footer(text="✨ Foil Edition")

    return embed


class _GarageBrowseView(discord.ui.View):
    """Interactive garage browser — select dropdown to inspect individual cards, back button to return."""  # noqa: E501

    def __init__(
        self,
        requester_id: int,
        target_name: str,
        user_cards: list,
        flavor: str,
    ) -> None:
        super().__init__(timeout=300)
        self.requester_id = requester_id
        self.target_name = target_name
        self.user_cards = user_cards
        self.flavor = flavor
        # Map user_card id str → (UserCard, Card) for quick lookup
        self._card_map: dict[str, tuple] = {}
        for uc in user_cards:
            self._card_map[str(uc.id)] = (uc, uc.card)

        self._build_select()

    def _build_select(self) -> None:
        """Populate the Select dropdown with card options (max 25)."""
        options = []
        for uc in self.user_cards[:25]:
            card = uc.card
            emoji_str = RARITY_EMOJI.get(card.rarity.value, "")
            foil = " ✨" if uc.is_foil else ""
            label = f"{card.name} #{uc.serial_number}"
            desc = f"{card.slot.value.title()} • {card.rarity.value.title()}{foil}"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    description=desc[:100],
                    value=str(uc.id),
                    emoji=emoji_str or None,
                )
            )

        if not options:
            return

        self.card_select = discord.ui.Select(
            placeholder="Select a part to inspect...",
            options=options,
            row=0,
        )
        self.card_select.callback = self._on_select
        self.add_item(self.card_select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This isn't your peek — hands off.", ephemeral=True
            )
            return

        uc_id = self.card_select.values[0]
        entry = self._card_map.get(uc_id)
        if not entry:
            await interaction.response.send_message("Card not found.", ephemeral=True)
            return

        uc, card = entry
        embed = _build_card_detail_embed(card, uc, self.target_name)

        # Swap to detail view: remove select, show Back button
        back_view = _GarageDetailView(self)
        await interaction.response.edit_message(embed=embed, view=back_view)

    @discord.ui.button(label="Close Garage", style=discord.ButtonStyle.secondary, emoji="🚪", row=1)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("This isn't your peek.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        embed = discord.Embed(
            title=f"🔍 {self.target_name}'s Garage",
            description="*You step out and the door shuts behind you.*",
            color=0x9CA3AF,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    async def on_timeout(self) -> None:
        # Can't easily edit on timeout without storing the message reference,
        # but the components will stop responding
        self.stop()


class _GarageDetailView(discord.ui.View):
    """Detail view for a single card — Back button returns to the inventory list."""

    def __init__(self, browse_view: _GarageBrowseView) -> None:
        super().__init__(timeout=300)
        self.browse_view = browse_view

    @discord.ui.button(label="Back to Inventory", style=discord.ButtonStyle.primary, emoji="🔙")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.browse_view.requester_id:
            await interaction.response.send_message("This isn't your peek.", ephemeral=True)
            return
        embed = _build_inventory_embed(
            self.browse_view.target_name,
            self.browse_view.requester_id,
            self.browse_view.user_cards,
            self.browse_view.flavor,
        )
        await interaction.response.edit_message(embed=embed, view=self.browse_view)

    @discord.ui.button(label="Close Garage", style=discord.ButtonStyle.secondary, emoji="🚪")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.browse_view.requester_id:
            await interaction.response.send_message("This isn't your peek.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"🔍 {self.browse_view.target_name}'s Garage",
            description="*You step out and the door shuts behind you.*",
            color=0x9CA3AF,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()


class _GarageRequestView(discord.ui.View):
    """Approve / deny another player peeking at your full garage."""

    DENY_LINES = [
        'The garage door stays shut. You hear a muffled "go away" from inside.',
        "A padlock clicks. That's a no.",
        "You hear power tools rev up. Probably best to leave.",
        "A sign flips to CLOSED. Real subtle.",
        '"Come back with a warrant." The slot in the door slams shut.',
    ]

    APPROVE_LINES = [
        'The garage door creaks open. "Make it quick."',
        "You knock twice. The door swings open and you're waved in.",
        '"Don\'t touch anything." They step aside and let you look.',
        'The lights flicker on. "Alright, feast your eyes."',
        'A grease-stained hand pulls you inside. "Check this out."',
    ]

    def __init__(self, requester_id: int, target_id: int, target_name: str) -> None:
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.target_id = target_id
        self.target_name = target_name

    @discord.ui.button(label="Let them in", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.target_id:
            await interaction.response.send_message("This isn't your garage.", ephemeral=True)
            return

        # Disable the accept/deny buttons
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        flavor = random.choice(self.APPROVE_LINES)

        # Fetch all of the target's cards
        async with async_session() as session:
            result = await session.execute(
                select(UserCard)
                .where(UserCard.user_id == str(self.target_id))
                .options(selectinload(UserCard.card))
                .order_by(UserCard.acquired_at)
            )
            user_cards = list(result.scalars().all())

        if not user_cards:
            embed = discord.Embed(
                title=f"🔍 {self.target_name}'s Garage",
                description=f"*{flavor}*\n\n<@{self.requester_id}>, the garage is... empty. Awkward.",  # noqa: E501
                color=0x9CA3AF,
            )
            await interaction.followup.send(embed=embed)
            self.stop()
            return

        embed = _build_inventory_embed(self.target_name, self.requester_id, user_cards, flavor)
        browse_view = _GarageBrowseView(
            requester_id=self.requester_id,
            target_name=self.target_name,
            user_cards=user_cards,
            flavor=flavor,
        )
        await interaction.followup.send(embed=embed, view=browse_view)
        self.stop()

    @discord.ui.button(label="Keep it locked", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.target_id:
            await interaction.response.send_message("This isn't your garage.", ephemeral=True)
            return

        flavor = random.choice(self.DENY_LINES)
        embed = discord.Embed(
            title="🔒 Garage Locked",
            description=f"*{flavor}*\n\nSorry <@{self.requester_id}>, no dice.",
            color=0xEF4444,
        )

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(embed=embed)
        self.stop()

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

    @app_commands.command(name="salvage", description="Salvage a part for Creds")
    @app_commands.describe(card_name="Name of the card to salvage (e.g. Card Name #3)")
    async def salvage(self, interaction: discord.Interaction, card_name: str) -> None:
        parsed_name, parsed_serial = _parse_card_input(card_name)

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            card_result = await session.execute(select(Card).where(Card.name == parsed_name))
            card = card_result.scalar_one_or_none()
            if not card:
                await interaction.response.send_message(
                    f"Card `{parsed_name}` not found.", ephemeral=True
                )
                return

            # Find the specific copy
            uc_query = (
                select(UserCard)
                .where(
                    UserCard.user_id == user.discord_id,
                    UserCard.card_id == card.id,
                )
                .order_by(UserCard.serial_number)
            )
            if parsed_serial is not None:
                uc_query = uc_query.where(UserCard.serial_number == parsed_serial)

            uc_result = await session.execute(uc_query.limit(1))
            uc = uc_result.scalar_one_or_none()
            if not uc:
                serial_hint = f" #{parsed_serial}" if parsed_serial is not None else ""
                await interaction.response.send_message(
                    f"You don't own `{card.name}`{serial_hint}.", ephemeral=True
                )
                return

            # Block if the card is equipped in any active build
            build_result = await session.execute(
                select(Build).where(Build.user_id == user.discord_id, Build.is_active)
            )
            build = build_result.scalar_one_or_none()
            if build and str(uc.id) in (build.slots or {}).values():
                await interaction.response.send_message(
                    f"⚠️ **{card.name}** is currently equipped. Unequip it first before salvaging.",
                    ephemeral=True,
                )
                return

            payout = _get_salvage_rates().get(card.rarity.value, 0)

            await session.delete(uc)
            user.currency += payout
            await session.commit()

        rarity_emoji = {
            Rarity.COMMON: "⬜",
            Rarity.UNCOMMON: "🟩",
            Rarity.RARE: "🟦",
            Rarity.EPIC: "🟪",
            Rarity.LEGENDARY: "🟨",
            Rarity.GHOST: "👻",
        }.get(card.rarity, "")
        serial_str = f" #{uc.serial_number}" if uc.serial_number else ""
        await interaction.response.send_message(
            f"🔧 Salvaged {rarity_emoji} **{card.name}**{serial_str} for **{payout} Creds**.",
            ephemeral=True,
        )

    @salvage.autocomplete("card_name")
    async def salvage_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await _card_copy_autocomplete(interaction, current)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CardsCog(bot))
