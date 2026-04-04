"""Market cog — /market, /list, /buy, /trade commands."""

from __future__ import annotations

import uuid

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from db.models import Card, MarketListing, User, UserCard
from db.session import async_session

log = get_logger(__name__)


async def _grant_card(session: AsyncSession, user_id: str, card_id: uuid.UUID) -> None:
    """Give a card to a user — increment quantity if they already own it."""
    result = await session.execute(
        select(UserCard).where(UserCard.user_id == user_id, UserCard.card_id == card_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.quantity += 1
    else:
        uc = UserCard(user_id=user_id, card_id=card_id, quantity=1)
        session.add(uc)


class TradeView(discord.ui.View):
    """View for confirming a trade between two players."""

    def __init__(
        self,
        initiator_id: int,
        target_id: int,
        initiator_card: Card,
        target_card: Card,
    ) -> None:
        super().__init__(timeout=120)
        self.initiator_id = initiator_id
        self.target_id = target_id
        self.initiator_card = initiator_card
        self.target_card = target_card
        self.accepted = False

    @discord.ui.button(label="Accept Trade", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.target_id:
            await interaction.response.send_message("Only the trade target can accept.", ephemeral=True)
            return

        async with async_session() as session:
            # Transfer cards
            # Decrement initiator's card
            init_uc = await session.execute(
                select(UserCard).where(
                    UserCard.user_id == str(self.initiator_id),
                    UserCard.card_id == self.initiator_card.id,
                )
            )
            init_card = init_uc.scalar_one_or_none()
            if not init_card or init_card.quantity <= 0:
                await interaction.response.send_message("Trade failed — initiator no longer has the card.", ephemeral=True)
                self.stop()
                return

            target_uc = await session.execute(
                select(UserCard).where(
                    UserCard.user_id == str(self.target_id),
                    UserCard.card_id == self.target_card.id,
                )
            )
            target_card = target_uc.scalar_one_or_none()
            if not target_card or target_card.quantity <= 0:
                await interaction.response.send_message("Trade failed — target no longer has the card.", ephemeral=True)
                self.stop()
                return

            init_card.quantity -= 1
            target_card.quantity -= 1

            await _grant_card(session, str(self.initiator_id), self.target_card.id)
            await _grant_card(session, str(self.target_id), self.initiator_card.id)
            await session.commit()

        self.accepted = True
        await interaction.response.send_message("✅ Trade completed!")
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.target_id:
            await interaction.response.send_message("Only the trade target can decline.", ephemeral=True)
            return
        await interaction.response.send_message("❌ Trade declined.")
        self.stop()


class MarketCog(commands.Cog):
    """Marketplace for buying, selling, and trading cards."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="market", description="Browse the marketplace")
    async def market(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            result = await session.execute(
                select(MarketListing)
                .where(MarketListing.sold_at == None)
                .order_by(MarketListing.listed_at.desc())
                .limit(20)
            )
            listings = list(result.scalars().all())

        if not listings:
            await interaction.response.send_message("The market is empty! Use `/list` to sell a card.", ephemeral=True)
            return

        lines = []
        for listing in listings:
            card = listing.card
            lines.append(
                f"**{card.name}** [{card.slot.value}] ({card.rarity.value}) — "
                f"**{listing.price} Creds** — Seller: <@{listing.seller_id}>"
            )

        embed = discord.Embed(
            title="🏪 Marketplace",
            description="\n".join(lines),
            color=0x22C55E,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="list", description="List a card for sale on the market")
    @app_commands.describe(card_name="Name of the card to sell", price="Asking price in Creds")
    async def list_card(self, interaction: discord.Interaction, card_name: str, price: int) -> None:
        if price <= 0:
            await interaction.response.send_message("Price must be positive.", ephemeral=True)
            return

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            card_result = await session.execute(select(Card).where(Card.name == card_name))
            card = card_result.scalar_one_or_none()
            if not card:
                await interaction.response.send_message(f"Card `{card_name}` not found.", ephemeral=True)
                return

            uc_result = await session.execute(
                select(UserCard).where(
                    UserCard.user_id == user.discord_id,
                    UserCard.card_id == card.id,
                )
            )
            uc = uc_result.scalar_one_or_none()
            if not uc or uc.quantity <= 0:
                await interaction.response.send_message("You don't own that card.", ephemeral=True)
                return

            listing = MarketListing(
                seller_id=user.discord_id,
                card_id=card.id,
                price=price,
            )
            session.add(listing)
            uc.quantity -= 1
            await session.commit()

        await interaction.response.send_message(
            f"📋 Listed **{card.name}** for **{price} Creds** on the market!"
        )

    @app_commands.command(name="buy", description="Buy a card from the market")
    @app_commands.describe(card_name="Name of the card to buy")
    async def buy(self, interaction: discord.Interaction, card_name: str) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            card_result = await session.execute(select(Card).where(Card.name == card_name))
            card = card_result.scalar_one_or_none()
            if not card:
                await interaction.response.send_message(f"Card `{card_name}` not found.", ephemeral=True)
                return

            listing_result = await session.execute(
                select(MarketListing).where(
                    MarketListing.card_id == card.id,
                    MarketListing.sold_at == None,
                ).order_by(MarketListing.price.asc()).limit(1)
            )
            listing = listing_result.scalar_one_or_none()
            if not listing:
                await interaction.response.send_message("No listings found for that card.", ephemeral=True)
                return

            if listing.seller_id == user.discord_id:
                await interaction.response.send_message("You can't buy your own listing.", ephemeral=True)
                return

            if user.currency < listing.price:
                await interaction.response.send_message(
                    f"Not enough Creds! Need {listing.price}, have {user.currency}.",
                    ephemeral=True,
                )
                return

            # Execute purchase
            from datetime import datetime, timezone

            user.currency -= listing.price
            seller = await session.get(User, listing.seller_id)
            if seller:
                seller.currency += listing.price
            listing.sold_at = datetime.now(timezone.utc)

            await _grant_card(session, user.discord_id, card.id)
            await session.commit()

        await interaction.response.send_message(
            f"🛒 Purchased **{card.name}** for **{listing.price} Creds**!"
        )

    @app_commands.command(name="trade", description="Initiate a card trade with another player")
    @app_commands.describe(
        target="Player to trade with",
        your_card="Card you're offering",
        their_card="Card you want in return",
    )
    async def trade(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        your_card: str,
        their_card: str,
    ) -> None:
        if target.id == interaction.user.id:
            await interaction.response.send_message("You can't trade with yourself.", ephemeral=True)
            return

        async with async_session() as session:
            # Validate both cards exist
            your_result = await session.execute(select(Card).where(Card.name == your_card))
            your_card_obj = your_result.scalar_one_or_none()
            their_result = await session.execute(select(Card).where(Card.name == their_card))
            their_card_obj = their_result.scalar_one_or_none()

            if not your_card_obj or not their_card_obj:
                await interaction.response.send_message("One or both cards not found.", ephemeral=True)
                return

            # Validate ownership
            your_uc = await session.execute(
                select(UserCard).where(
                    UserCard.user_id == str(interaction.user.id),
                    UserCard.card_id == your_card_obj.id,
                )
            )
            if not (uc := your_uc.scalar_one_or_none()) or uc.quantity <= 0:
                await interaction.response.send_message(f"You don't own `{your_card}`.", ephemeral=True)
                return

            their_uc = await session.execute(
                select(UserCard).where(
                    UserCard.user_id == str(target.id),
                    UserCard.card_id == their_card_obj.id,
                )
            )
            if not (tuc := their_uc.scalar_one_or_none()) or tuc.quantity <= 0:
                await interaction.response.send_message(
                    f"{target.display_name} doesn't own `{their_card}`.", ephemeral=True
                )
                return

        view = TradeView(
            initiator_id=interaction.user.id,
            target_id=target.id,
            initiator_card=your_card_obj,
            target_card=their_card_obj,
        )
        embed = discord.Embed(
            title="🔄 Trade Offer",
            description=(
                f"**{interaction.user.display_name}** offers: **{your_card}**\n"
                f"**{target.display_name}** offers: **{their_card}**\n\n"
                f"{target.mention}, accept or decline?"
            ),
            color=0xF59E0B,
        )
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketCog(bot))
