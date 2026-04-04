"""Garage cog — /start, /garage, /equip, /build commands."""

from __future__ import annotations

import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from config.settings import settings
from db.models import BodyType, Build, Card, CardSlot, User, UserCard
from db.session import async_session

log = get_logger(__name__)

BODY_EMOJI = {
    BodyType.MUSCLE: "💪",
    BodyType.SPORT: "🏎️",
    BodyType.COMPACT: "🚗",
}


class BodyTypeSelect(discord.ui.View):
    """Button-based body type selector for /start."""

    def __init__(self, user_id: int, username: str) -> None:
        super().__init__(timeout=60)
        self.user_id = user_id
        self.username = username
        self.chosen: BodyType | None = None

    async def _handle_choice(self, interaction: discord.Interaction, body_type: BodyType) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your selection!", ephemeral=True)
            return

        self.chosen = body_type
        async with async_session() as session:
            existing = await session.get(User, str(self.user_id))
            if existing:
                await interaction.response.send_message("You already have an account!", ephemeral=True)
                self.stop()
                return

            user = User(
                discord_id=str(self.user_id),
                username=self.username,
                body_type=body_type,
                currency=settings.STARTING_CURRENCY,
                xp=0,
            )
            session.add(user)

            # Create default empty build
            build = Build(
                user_id=str(self.user_id),
                name="My Build",
                slots={slot.value: None for slot in CardSlot},
                is_active=True,
            )
            session.add(build)
            await session.commit()

        emoji = BODY_EMOJI.get(body_type, "🚗")
        embed = discord.Embed(
            title=f"{emoji} Welcome to Dare2Drive!",
            description=(
                f"**Body Type:** {body_type.value.title()}\n"
                f"**Starting Creds:** {settings.STARTING_CURRENCY}\n\n"
                "Use `/pack` to open your first card pack!\n"
                "Use `/garage` to see your build."
            ),
            color=0x22C55E,
        )
        await interaction.response.send_message(embed=embed)
        self.stop()

    @discord.ui.button(label="💪 Muscle", style=discord.ButtonStyle.danger)
    async def muscle_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_choice(interaction, BodyType.MUSCLE)

    @discord.ui.button(label="🏎️ Sport", style=discord.ButtonStyle.primary)
    async def sport_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_choice(interaction, BodyType.SPORT)

    @discord.ui.button(label="🚗 Compact", style=discord.ButtonStyle.secondary)
    async def compact_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_choice(interaction, BodyType.COMPACT)


class GarageCog(commands.Cog):
    """Garage management — body selection, build viewing, equipping."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="start", description="Create your Dare2Drive account and pick a body type")
    async def start(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            existing = await session.get(User, str(interaction.user.id))
            if existing:
                await interaction.response.send_message("You already have an account!", ephemeral=True)
                return

        view = BodyTypeSelect(interaction.user.id, interaction.user.display_name)
        embed = discord.Embed(
            title="🏁 Choose Your Body Type",
            description=(
                "Pick your ride's identity. This is permanent and cosmetic only.\n\n"
                "💪 **Muscle** — Raw American power\n"
                "🏎️ **Sport** — Sleek and agile\n"
                "🚗 **Compact** — Light and nimble"
            ),
            color=0xF59E0B,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="garage", description="View your current build")
    async def garage(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            result = await session.execute(
                select(Build).where(Build.user_id == user.discord_id, Build.is_active == True)
            )
            build = result.scalar_one_or_none()
            if not build:
                await interaction.response.send_message("No active build found.", ephemeral=True)
                return

            # Resolve card names for each slot
            slot_lines = []
            warnings = []
            for slot in CardSlot:
                card_id = build.slots.get(slot.value)
                if card_id:
                    card = await session.get(Card, uuid.UUID(card_id))
                    if card:
                        # Check user owns it with quantity > 0
                        uc_result = await session.execute(
                            select(UserCard).where(
                                UserCard.user_id == user.discord_id,
                                UserCard.card_id == card.id,
                            )
                        )
                        uc = uc_result.scalar_one_or_none()
                        qty_warning = ""
                        if uc and uc.quantity <= 0:
                            qty_warning = " ⚠️ **QUANTITY 0 — UNEQUIP NEEDED**"
                            warnings.append(slot.value)
                        slot_lines.append(
                            f"**{slot.value.title()}:** {card.name} ({card.rarity.value}){qty_warning}"
                        )
                    else:
                        slot_lines.append(f"**{slot.value.title()}:** ❌ Card not found")
                else:
                    slot_lines.append(f"**{slot.value.title()}:** — Empty —")

        emoji = BODY_EMOJI.get(user.body_type, "🚗")
        embed = discord.Embed(
            title=f"{emoji} {interaction.user.display_name}'s Garage",
            description=f"**Body Type:** {user.body_type.value.title()}\n**Build:** {build.name}\n\n"
            + "\n".join(slot_lines),
            color=0x3B82F6,
        )
        embed.add_field(name="Creds", value=str(user.currency), inline=True)
        embed.add_field(name="XP", value=str(user.xp), inline=True)

        if warnings:
            embed.add_field(
                name="⚠️ Warning",
                value=f"Slots with quantity 0: {', '.join(warnings)}. You cannot race until fixed!",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="equip", description="Equip a card to a build slot")
    @app_commands.describe(slot="The slot to equip into", card_name="Name of the card to equip")
    @app_commands.choices(slot=[
        app_commands.Choice(name=s.value.title(), value=s.value) for s in CardSlot
    ])
    async def equip(self, interaction: discord.Interaction, slot: str, card_name: str) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            # Find the card
            card_result = await session.execute(select(Card).where(Card.name == card_name))
            card = card_result.scalar_one_or_none()
            if not card:
                await interaction.response.send_message(f"Card `{card_name}` not found.", ephemeral=True)
                return

            # Validate slot matches
            if card.slot.value != slot:
                await interaction.response.send_message(
                    f"`{card.name}` is a **{card.slot.value}** card and can't go in the **{slot}** slot.",
                    ephemeral=True,
                )
                return

            # Check ownership with quantity > 0
            uc_result = await session.execute(
                select(UserCard).where(
                    UserCard.user_id == user.discord_id,
                    UserCard.card_id == card.id,
                )
            )
            uc = uc_result.scalar_one_or_none()
            if not uc or uc.quantity <= 0:
                await interaction.response.send_message(
                    f"You don't own `{card.name}` (or quantity is 0).", ephemeral=True
                )
                return

            # Get active build
            build_result = await session.execute(
                select(Build).where(Build.user_id == user.discord_id, Build.is_active == True)
            )
            build = build_result.scalar_one_or_none()
            if not build:
                await interaction.response.send_message("No active build found.", ephemeral=True)
                return

            # Equip
            new_slots = dict(build.slots)
            new_slots[slot] = str(card.id)
            build.slots = new_slots
            await session.commit()

        await interaction.response.send_message(
            f"✅ Equipped **{card.name}** in the **{slot.title()}** slot!"
        )

    @app_commands.command(name="profile", description="View your profile")
    async def profile(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

        emoji = BODY_EMOJI.get(user.body_type, "🚗")
        embed = discord.Embed(
            title=f"{emoji} {user.username}",
            color=0x3B82F6,
        )
        embed.add_field(name="Body Type", value=user.body_type.value.title(), inline=True)
        embed.add_field(name="Creds", value=str(user.currency), inline=True)
        embed.add_field(name="XP", value=str(user.xp), inline=True)
        embed.set_footer(text=f"Member since {user.created_at.strftime('%Y-%m-%d') if user.created_at else 'unknown'}")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GarageCog(bot))
