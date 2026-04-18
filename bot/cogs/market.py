"""Market cog — /market, /list, /buy, /trade, /shop, /salvage commands."""

from __future__ import annotations

import uuid

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.metrics import currency_spent
from config.logging import get_logger
from config.metrics import trace_exemplar
from config.tracing import traced_command
from db.models import Build, Card, CardSlot, MarketListing, User, UserCard
from db.session import async_session

log = get_logger(__name__)

# NPC shop — fixed price per slot for common parts
NPC_SHOP_PRICES: dict[str, int] = {
    "engine": 150,
    "transmission": 120,
    "tires": 100,
    "chassis": 130,
    "brakes": 100,
    "suspension": 110,
    "turbo": 200,
}

# Salvage payout by rarity
SALVAGE_VALUES: dict[str, int] = {
    "common": 15,
    "uncommon": 40,
    "rare": 100,
    "epic": 300,
    "legendary": 800,
    "ghost": 2000,
}


async def _unequip_user_card(session: AsyncSession, user_id: str, user_card_id: str) -> None:
    """Remove a specific UserCard from the user's active build slots."""
    result = await session.execute(select(Build).where(Build.user_id == user_id, Build.is_active))
    build = result.scalar_one_or_none()
    if not build:
        return
    new_slots = dict(build.slots)
    changed = False
    for slot_name, uc_id in new_slots.items():
        if uc_id == user_card_id:
            new_slots[slot_name] = None
            changed = True
    if changed:
        build.slots = new_slots


async def _has_active_listing(session: AsyncSession, user_card_id: uuid.UUID) -> bool:
    """Check if a UserCard is currently listed on the market (unsold)."""
    result = await session.execute(
        select(MarketListing.id)
        .where(
            MarketListing.user_card_id == user_card_id,
            MarketListing.sold_at is None,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


RARITY_EMOJI = {
    "common": "⬜",
    "uncommon": "🟩",
    "rare": "🟦",
    "epic": "🟪",
    "legendary": "🟨",
    "ghost": "👻",
}

RARITY_COLORS = {
    "common": 0x9CA3AF,
    "uncommon": 0x22C55E,
    "rare": 0x3B82F6,
    "epic": 0xA855F7,
    "legendary": 0xF59E0B,
    "ghost": 0xFFFFFF,
}


def _build_market_embed(listing_data: list[dict]) -> discord.Embed:
    """Build the marketplace listing embed."""
    lines = []
    for entry in listing_data:
        card = entry["card"]
        uc = entry["user_card"]
        listing = entry["listing"]
        emoji = RARITY_EMOJI.get(card.rarity.value, "")
        lines.append(
            f"{emoji} **{card.name}** #{uc.serial_number} [{card.slot.value}] ({card.rarity.value}) — "  # noqa: E501
            f"**{listing.price} Creds** — Seller: <@{listing.seller_id}>"
        )

    embed = discord.Embed(
        title="🏪 Marketplace",
        description="\n".join(lines),
        color=0x22C55E,
    )
    embed.set_footer(text="Select a listing below to inspect the part")
    return embed


def _build_market_detail_embed(entry: dict) -> discord.Embed:
    """Build a full stat inspect embed for a market listing."""
    from engine.card_mint import apply_stat_modifiers

    card = entry["card"]
    uc = entry["user_card"]
    listing = entry["listing"]

    effective_stats = apply_stat_modifiers(card.stats, uc.stat_modifiers or {})

    color = RARITY_COLORS.get(card.rarity.value, 0x9CA3AF)
    emoji = RARITY_EMOJI.get(card.rarity.value, "")
    embed = discord.Embed(
        title=f"{emoji} {card.name} #{uc.serial_number}",
        description=f"**Price: {listing.price} Creds** — Seller: <@{listing.seller_id}>",
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


class _MarketBrowseView(discord.ui.View):
    """Interactive market browser — select a listing to inspect it."""

    def __init__(self, listing_data: list[dict], viewer_id: int) -> None:
        super().__init__(timeout=300)
        self.listing_data = listing_data
        self.viewer_id = viewer_id
        self._entry_map: dict[str, dict] = {}

        options = []
        for entry in listing_data[:25]:
            card = entry["card"]
            uc = entry["user_card"]
            listing = entry["listing"]
            key = str(listing.id)
            self._entry_map[key] = entry

            emoji = RARITY_EMOJI.get(card.rarity.value, "")
            label = f"{card.name} #{uc.serial_number}"
            desc = f"{card.slot.value.title()} • {listing.price} Creds"
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    description=desc[:100],
                    value=key,
                    emoji=emoji or None,
                )
            )

        if options:
            self.listing_select = discord.ui.Select(
                placeholder="Select a listing to inspect...",
                options=options,
                row=0,
            )
            self.listing_select.callback = self._on_select
            self.add_item(self.listing_select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        key = self.listing_select.values[0]
        entry = self._entry_map.get(key)
        if not entry:
            await interaction.response.send_message("Listing not found.", ephemeral=True)
            return

        embed = _build_market_detail_embed(entry)
        detail_view = _MarketDetailView(self)
        await interaction.response.edit_message(embed=embed, view=detail_view)

    @discord.ui.button(label="Close Market", style=discord.ButtonStyle.secondary, emoji="🚪", row=1)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = discord.Embed(
            title="🏪 Marketplace",
            description="*You walk away from the market.*",
            color=0x9CA3AF,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    async def on_timeout(self) -> None:
        self.stop()


class _MarketDetailView(discord.ui.View):
    """Detail view for a single market listing — Back returns to the listing list."""

    def __init__(self, browse_view: _MarketBrowseView) -> None:
        super().__init__(timeout=300)
        self.browse_view = browse_view

    @discord.ui.button(label="Back to Market", style=discord.ButtonStyle.primary, emoji="🔙")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = _build_market_embed(self.browse_view.listing_data)
        await interaction.response.edit_message(embed=embed, view=self.browse_view)

    @discord.ui.button(label="Close Market", style=discord.ButtonStyle.secondary, emoji="🚪")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = discord.Embed(
            title="🏪 Marketplace",
            description="*You walk away from the market.*",
            color=0x9CA3AF,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()


class TradeView(discord.ui.View):
    """View for confirming a trade between two players."""

    def __init__(
        self,
        initiator_id: int,
        target_id: int,
        initiator_uc: UserCard,
        target_uc: UserCard,
        initiator_card: Card,
        target_card: Card,
    ) -> None:
        super().__init__(timeout=120)
        self.initiator_id = initiator_id
        self.target_id = target_id
        self.initiator_uc = initiator_uc
        self.target_uc = target_uc
        self.initiator_card = initiator_card
        self.target_card = target_card
        self.accepted = False

    @discord.ui.button(label="Accept Trade", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.target_id:
            await interaction.response.send_message(
                "Only the trade target can accept.", ephemeral=True
            )
            return

        async with async_session() as session:
            # Re-fetch both UserCards to ensure they still exist and are owned correctly
            init_uc = await session.get(UserCard, self.initiator_uc.id)
            target_uc = await session.get(UserCard, self.target_uc.id)

            if not init_uc or init_uc.user_id != str(self.initiator_id):
                await interaction.response.send_message(
                    "Trade failed — initiator no longer has the card.", ephemeral=True
                )
                self.stop()
                return

            if not target_uc or target_uc.user_id != str(self.target_id):
                await interaction.response.send_message(
                    "Trade failed — target no longer has the card.", ephemeral=True
                )
                self.stop()
                return

            # Check neither card is listed on the market
            if await _has_active_listing(session, init_uc.id):
                await interaction.response.send_message(
                    "Trade failed — initiator's card is listed on the market.", ephemeral=True
                )
                self.stop()
                return
            if await _has_active_listing(session, target_uc.id):
                await interaction.response.send_message(
                    "Trade failed — target's card is listed on the market.", ephemeral=True
                )
                self.stop()
                return

            # Unequip both cards from their owners' builds
            await _unequip_user_card(session, str(self.initiator_id), str(init_uc.id))
            await _unequip_user_card(session, str(self.target_id), str(target_uc.id))

            # Swap ownership
            init_uc.user_id = str(self.target_id)
            target_uc.user_id = str(self.initiator_id)

            await session.commit()

        self.accepted = True
        await interaction.response.send_message("✅ Trade completed!")
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.target_id:
            await interaction.response.send_message(
                "Only the trade target can decline.", ephemeral=True
            )
            return
        await interaction.response.send_message("❌ Trade declined.")
        self.stop()


class MarketCog(commands.Cog):
    """Marketplace for buying, selling, and trading cards."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="market", description="Browse the marketplace")
    @traced_command
    async def market(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            result = await session.execute(
                select(MarketListing)
                .where(MarketListing.sold_at is None)
                .order_by(MarketListing.listed_at.desc())
                .limit(25)
            )
            listings = list(result.scalars().all())

            if not listings:
                await interaction.response.send_message(
                    "The market is empty! Use `/list` to sell a card.", ephemeral=True
                )
                return

            # Resolve all listing data upfront
            listing_data: list[dict] = []
            for listing in listings:
                uc = await session.get(UserCard, listing.user_card_id)
                card = await session.get(Card, listing.card_id)
                if not card or not uc:
                    continue
                listing_data.append(
                    {
                        "listing": listing,
                        "card": card,
                        "user_card": uc,
                    }
                )

        if not listing_data:
            await interaction.response.send_message(
                "The market is empty! Use `/list` to sell a card.", ephemeral=True
            )
            return

        embed = _build_market_embed(listing_data)
        view = _MarketBrowseView(listing_data=listing_data, viewer_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="list", description="List a card for sale on the market")
    @app_commands.describe(
        card_name="Name of the card to sell (e.g. Card Name #3)", price="Asking price in Creds"
    )
    @traced_command
    async def list_card(self, interaction: discord.Interaction, card_name: str, price: int) -> None:
        from bot.cogs.cards import _parse_card_input

        if price <= 0:
            await interaction.response.send_message("Price must be positive.", ephemeral=True)
            return

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

            # If a specific serial was given, find that exact copy
            if parsed_serial is not None:
                uc_result = await session.execute(
                    select(UserCard)
                    .where(
                        UserCard.user_id == user.discord_id,
                        UserCard.card_id == card.id,
                        UserCard.serial_number == parsed_serial,
                    )
                    .limit(1)
                )
                chosen = uc_result.scalar_one_or_none()
                if not chosen:
                    await interaction.response.send_message(
                        f"You don't own `{card.name}` #{parsed_serial}.", ephemeral=True
                    )
                    return
                if await _has_active_listing(session, chosen.id):
                    await interaction.response.send_message(
                        "That copy is already listed on the market.", ephemeral=True
                    )
                    return
            else:
                # Auto-pick: prefer unequipped, unlisted copies
                uc_result = await session.execute(
                    select(UserCard)
                    .where(
                        UserCard.user_id == user.discord_id,
                        UserCard.card_id == card.id,
                    )
                    .order_by(UserCard.serial_number)
                )
                copies = list(uc_result.scalars().all())
                if not copies:
                    await interaction.response.send_message(
                        "You don't own that card.", ephemeral=True
                    )
                    return

                build_result = await session.execute(
                    select(Build).where(Build.user_id == user.discord_id, Build.is_active)
                )
                build = build_result.scalar_one_or_none()
                equipped_ids = set()
                if build:
                    equipped_ids = {uc_id for uc_id in build.slots.values() if uc_id is not None}

                chosen = None
                for uc in copies:
                    if str(uc.id) in equipped_ids:
                        continue
                    if await _has_active_listing(session, uc.id):
                        continue
                    chosen = uc
                    break

                if chosen is None:
                    for uc in copies:
                        if await _has_active_listing(session, uc.id):
                            continue
                        chosen = uc
                        break

                if chosen is None:
                    await interaction.response.send_message(
                        "All your copies of that card are already listed on the market.",
                        ephemeral=True,
                    )
                    return

            # Unequip from build if equipped
            await _unequip_user_card(session, user.discord_id, str(chosen.id))

            listing = MarketListing(
                seller_id=user.discord_id,
                card_id=card.id,
                user_card_id=chosen.id,
                price=price,
            )
            session.add(listing)
            await session.commit()

        await interaction.response.send_message(
            f"📋 Listed **{card.name}** #{chosen.serial_number} for **{price} Creds** on the market!"  # noqa: E501
        )

    @list_card.autocomplete("card_name")
    async def list_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        from bot.cogs.cards import _card_copy_autocomplete

        return await _card_copy_autocomplete(interaction, current)

    @app_commands.command(name="buy", description="Buy a card from the market")
    @app_commands.describe(card_name="Name of the card to buy")
    @traced_command
    async def buy(self, interaction: discord.Interaction, card_name: str) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            card_result = await session.execute(select(Card).where(Card.name == card_name))
            card = card_result.scalar_one_or_none()
            if not card:
                await interaction.response.send_message(
                    f"Card `{card_name}` not found.", ephemeral=True
                )
                return

            # Find the cheapest unsold listing for this card
            listing_result = await session.execute(
                select(MarketListing)
                .where(
                    MarketListing.card_id == card.id,
                    MarketListing.sold_at is None,
                )
                .order_by(MarketListing.price.asc())
                .limit(1)
            )
            listing = listing_result.scalar_one_or_none()
            if not listing:
                await interaction.response.send_message(
                    "No listings found for that card.", ephemeral=True
                )
                return

            if listing.seller_id == user.discord_id:
                await interaction.response.send_message(
                    "You can't buy your own listing.", ephemeral=True
                )
                return

            if user.currency < listing.price:
                await interaction.response.send_message(
                    f"Not enough Creds! Need {listing.price}, have {user.currency}.",
                    ephemeral=True,
                )
                return

            # Verify the UserCard still exists
            uc = await session.get(UserCard, listing.user_card_id)
            if not uc:
                await interaction.response.send_message(
                    "That card copy no longer exists (wrecked?).", ephemeral=True
                )
                return

            # Execute purchase — transfer ownership of the exact copy
            from datetime import datetime, timezone

            user.currency -= listing.price
            currency_spent.labels(reason="market_buy").inc(listing.price, exemplar=trace_exemplar())
            seller = await session.get(User, listing.seller_id)
            if seller:
                seller.currency += listing.price
            listing.sold_at = datetime.now(timezone.utc)

            # Transfer the specific card copy to the buyer
            uc.user_id = user.discord_id
            await session.commit()

        await interaction.response.send_message(
            f"🛒 Purchased **{card.name}** #{uc.serial_number} for **{listing.price} Creds**!"
        )

    @buy.autocomplete("card_name")
    async def buy_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Show cards currently listed on the market."""
        async with async_session() as session:
            result = await session.execute(
                select(Card.name)
                .join(MarketListing, MarketListing.card_id == Card.id)
                .where(
                    MarketListing.sold_at is None,
                    Card.name.ilike(f"%{current}%"),
                )
                .distinct()
                .order_by(Card.name)
                .limit(25)
            )
            names = result.scalars().all()
        return [app_commands.Choice(name=n, value=n) for n in names]

    @app_commands.command(name="trade", description="Initiate a card trade with another player")
    @app_commands.describe(
        target="Player to trade with",
        your_card="Card you're offering",
        their_card="Card you want in return",
    )
    @traced_command
    async def trade(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        your_card: str,
        their_card: str,
    ) -> None:
        if target.id == interaction.user.id:
            await interaction.response.send_message(
                "You can't trade with yourself.", ephemeral=True
            )
            return

        async with async_session() as session:
            # Validate both cards exist
            your_result = await session.execute(select(Card).where(Card.name == your_card))
            your_card_obj = your_result.scalar_one_or_none()
            their_result = await session.execute(select(Card).where(Card.name == their_card))
            their_card_obj = their_result.scalar_one_or_none()

            if not your_card_obj or not their_card_obj:
                await interaction.response.send_message(
                    "One or both cards not found.", ephemeral=True
                )
                return

            # Find initiator's copy (prefer unequipped, unlisted)
            your_uc_result = await session.execute(
                select(UserCard)
                .where(
                    UserCard.user_id == str(interaction.user.id),
                    UserCard.card_id == your_card_obj.id,
                )
                .order_by(UserCard.serial_number)
            )
            your_copies = list(your_uc_result.scalars().all())
            your_uc = None
            for uc in your_copies:
                if not await _has_active_listing(session, uc.id):
                    your_uc = uc
                    break
            if not your_uc:
                await interaction.response.send_message(
                    f"You don't have an available copy of `{your_card}` (all listed on market?).",
                    ephemeral=True,
                )
                return

            # Find target's copy
            their_uc_result = await session.execute(
                select(UserCard)
                .where(
                    UserCard.user_id == str(target.id),
                    UserCard.card_id == their_card_obj.id,
                )
                .order_by(UserCard.serial_number)
            )
            their_copies = list(their_uc_result.scalars().all())
            their_uc = None
            for uc in their_copies:
                if not await _has_active_listing(session, uc.id):
                    their_uc = uc
                    break
            if not their_uc:
                await interaction.response.send_message(
                    f"{target.display_name} doesn't have an available copy of `{their_card}`.",
                    ephemeral=True,
                )
                return

        view = TradeView(
            initiator_id=interaction.user.id,
            target_id=target.id,
            initiator_uc=your_uc,
            target_uc=their_uc,
            initiator_card=your_card_obj,
            target_card=their_card_obj,
        )
        your_emoji = RARITY_EMOJI.get(your_card_obj.rarity.value, "")
        their_emoji = RARITY_EMOJI.get(their_card_obj.rarity.value, "")
        embed = discord.Embed(
            title="🔄 Trade Offer",
            description=(
                f"**{interaction.user.display_name}** offers: {your_emoji} **{your_card}** #{your_uc.serial_number} "  # noqa: E501
                f"({your_card_obj.rarity.value.title()})\n"
                f"**{target.display_name}** offers: {their_emoji} **{their_card}** #{their_uc.serial_number} "  # noqa: E501
                f"({their_card_obj.rarity.value.title()})\n\n"
                f"{target.mention}, accept or decline?"
            ),
            color=RARITY_COLORS.get(their_card_obj.rarity.value, 0xF59E0B),
        )
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="shop", description="Browse the NPC parts shop — common parts always in stock"
    )
    @traced_command
    async def shop(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            lines = []
            for slot in CardSlot:
                price = NPC_SHOP_PRICES.get(slot.value, 100)
                # Pick the first common card for this slot (alphabetically)
                result = await session.execute(
                    select(Card)
                    .where(Card.slot == slot.value, Card.rarity == "common")
                    .order_by(Card.name)
                    .limit(1)
                )
                card = result.scalar_one_or_none()
                if card:
                    lines.append(f"⬜ **{card.name}** [{slot.value.title()}] — **{price} Creds**")

        if not lines:
            await interaction.response.send_message(
                "Shop is empty — no common cards in the database!", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🏪 Parts Shop",
            description=(
                "Basic parts, always in stock. Use `/shop_buy slot:Engine` to purchase.\n\n"
                + "\n".join(lines)
                + f"\n\n💰 Your balance: **{user.currency} Creds**"
            ),
            color=0x6B7280,
        )
        embed.set_footer(text="Salvage unwanted parts with /salvage")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="shop_buy", description="Buy a common part from the NPC shop")
    @app_commands.describe(slot="Which slot to buy a part for")
    @app_commands.choices(
        slot=[app_commands.Choice(name=s.value.title(), value=s.value) for s in CardSlot]
    )
    @traced_command
    async def shop_buy(self, interaction: discord.Interaction, slot: str) -> None:
        from engine.card_mint import mint_card

        price = NPC_SHOP_PRICES.get(slot, 100)

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            if user.currency < price:
                await interaction.response.send_message(
                    f"Not enough Creds! Need **{price}**, have **{user.currency}**.", ephemeral=True
                )
                return

            # Pick the first common card for this slot
            result = await session.execute(
                select(Card)
                .where(Card.slot == slot, Card.rarity == "common")
                .order_by(Card.name)
                .limit(1)
            )
            card = result.scalar_one_or_none()
            if not card:
                await interaction.response.send_message(
                    f"No common {slot} parts available.", ephemeral=True
                )
                return

            user.currency -= price
            currency_spent.labels(reason="shop_buy").inc(price, exemplar=trace_exemplar())
            uc = await mint_card(session, user.discord_id, card)
            await session.commit()

        await interaction.response.send_message(
            f"🛒 Bought **{card.name}** #{uc.serial_number} for **{price} Creds**!"
        )

    @app_commands.command(name="salvage", description="Scrap a card for Creds")
    @app_commands.describe(card_name="Card to salvage (e.g. Card Name #3)")
    @traced_command
    async def salvage(self, interaction: discord.Interaction, card_name: str) -> None:
        from bot.cogs.cards import _parse_card_input

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
            if parsed_serial is not None:
                uc_result = await session.execute(
                    select(UserCard)
                    .where(
                        UserCard.user_id == user.discord_id,
                        UserCard.card_id == card.id,
                        UserCard.serial_number == parsed_serial,
                    )
                    .limit(1)
                )
                chosen = uc_result.scalar_one_or_none()
                if not chosen:
                    await interaction.response.send_message(
                        f"You don't own `{card.name}` #{parsed_serial}.", ephemeral=True
                    )
                    return
            else:
                # Auto-pick: prefer unequipped, unlisted copies
                uc_result = await session.execute(
                    select(UserCard)
                    .where(
                        UserCard.user_id == user.discord_id,
                        UserCard.card_id == card.id,
                    )
                    .order_by(UserCard.serial_number)
                )
                copies = list(uc_result.scalars().all())
                if not copies:
                    await interaction.response.send_message(
                        "You don't own that card.", ephemeral=True
                    )
                    return

                build_result = await session.execute(
                    select(Build).where(Build.user_id == user.discord_id, Build.is_active)
                )
                build = build_result.scalar_one_or_none()
                equipped_ids = set()
                if build:
                    equipped_ids = {uc_id for uc_id in build.slots.values() if uc_id is not None}

                chosen = None
                for uc in copies:
                    if str(uc.id) in equipped_ids:
                        continue
                    if await _has_active_listing(session, uc.id):
                        continue
                    chosen = uc
                    break

                if chosen is None:
                    await interaction.response.send_message(
                        "All copies are equipped or listed. Unequip or delist one first.",
                        ephemeral=True,
                    )
                    return

            # Block salvaging equipped or listed cards
            if await _has_active_listing(session, chosen.id):
                await interaction.response.send_message(
                    "That copy is listed on the market. Delist it first.", ephemeral=True
                )
                return

            # Unequip if somehow still equipped
            await _unequip_user_card(session, user.discord_id, str(chosen.id))

            payout = SALVAGE_VALUES.get(card.rarity.value, 10)
            user.currency += payout
            await session.delete(chosen)
            await session.commit()

        emoji = RARITY_EMOJI.get(card.rarity.value, "")
        await interaction.response.send_message(
            f"🔧 Salvaged {emoji} **{card.name}** #{chosen.serial_number} for **{payout} Creds**!"
        )

    @salvage.autocomplete("card_name")
    async def salvage_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        from bot.cogs.cards import _card_copy_autocomplete

        return await _card_copy_autocomplete(interaction, current)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketCog(bot))
