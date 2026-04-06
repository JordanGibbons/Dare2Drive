"""Garage cog — /start, /garage, /equip, /build commands."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import get_logger
from config.settings import settings
from db.models import BodyType, Build, Card, CardSlot, TutorialStep, User, UserCard
from db.session import async_session

log = get_logger(__name__)

BODY_EMOJI = {
    BodyType.MUSCLE: "💪",
    BodyType.SPORT: "🏎️",
    BodyType.COMPACT: "🚗",
}

RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4, "ghost": 5}
RARITY_EMOJI = {"common": "⬜", "uncommon": "🟩", "rare": "🟦", "epic": "🟪", "legendary": "🟨", "ghost": "👻"}
RARITY_COLORS = {"common": 0x9CA3AF, "uncommon": 0x22C55E, "rare": 0x3B82F6, "epic": 0xA855F7, "legendary": 0xF59E0B, "ghost": 0xFFFFFF}


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
        await interaction.response.defer()

        async with async_session() as session:
            existing = await session.get(User, str(self.user_id))
            if existing:
                await interaction.followup.send("You already have an account!", ephemeral=True)
                self.stop()
                return

            user = User(
                discord_id=str(self.user_id),
                username=self.username,
                body_type=body_type,
                currency=0,
                xp=0,
                tutorial_step=TutorialStep.STARTED,
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

        # ── TUTORIAL STORY BEGINS ──
        from bot.cogs.tutorial import send_dialogue, grant_starter_cards, _load_tutorial_data
        data = _load_tutorial_data()
        dialogue = data["dialogue"]
        uid = self.user_id  # int

        # Act 1: The Inheritance
        emoji = BODY_EMOJI.get(body_type, "🚗")
        embed = discord.Embed(
            title=f"{emoji} Welcome to Dare2Drive!",
            description=f"**Body Type:** {body_type.value.title()}",
            color=0x22C55E,
        )
        await interaction.followup.send(embed=embed)

        view = await send_dialogue(
            interaction,
            dialogue["intro_inherited"],
            title="💰 The Inheritance",
            color=0x22C55E,
            with_continue=True,
            user_id=uid,
        )
        await view.wait_for_click()

        # Act 2: The Robbery
        view = await send_dialogue(
            interaction,
            dialogue["robbed"],
            title="💀 Welcome to the Strip",
            color=0xEF4444,
            with_continue=True,
            user_id=uid,
        )
        await view.wait_for_click()

        # Act 3: The Junkyard
        view = await send_dialogue(
            interaction,
            dialogue["junkyard"],
            title="🔩 The Junkyard",
            color=0x6B7280,
            with_continue=True,
            user_id=uid,
        )
        await view.wait_for_click()

        # Grant starter cards
        async with async_session() as session:
            user = await session.get(User, str(self.user_id))
            granted = await grant_starter_cards(session, user)

            card_lines = [f"**{card.name}** [{card.slot.value.title()}]" for card in granted]
            embed = discord.Embed(
                title="📦 Parts Found",
                description="You pulled these out of the scrap heap:\n\n" + "\n".join(card_lines),
                color=0xF59E0B,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            # Advance to INVENTORY step
            user.tutorial_step = TutorialStep.INVENTORY
            await session.commit()

        # Teach /inventory
        await send_dialogue(
            interaction,
            dialogue["teach_inventory"],
            title="🗃️ Check Your Loot",
        )

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

            # Resolve card names for each slot (slots now store user_card_id)
            slot_lines = []
            best_rarity = "common"
            for slot in CardSlot:
                uc_id_str = build.slots.get(slot.value)
                if uc_id_str:
                    uc = await session.get(UserCard, uuid.UUID(uc_id_str))
                    if uc:
                        card = await session.get(Card, uc.card_id)
                        if card:
                            r_emoji = RARITY_EMOJI.get(card.rarity.value, "")
                            slot_lines.append(
                                f"**{slot.value.title()}:** {r_emoji} {card.name} #{uc.serial_number} ({card.rarity.value})"
                            )
                            if RARITY_ORDER.get(card.rarity.value, 0) > RARITY_ORDER.get(best_rarity, 0):
                                best_rarity = card.rarity.value
                        else:
                            slot_lines.append(f"**{slot.value.title()}:** ❌ Card not found")
                    else:
                        slot_lines.append(f"**{slot.value.title()}:** ❌ Part missing (wrecked?)")
                else:
                    slot_lines.append(f"**{slot.value.title()}:** — Empty —")

        emoji = BODY_EMOJI.get(user.body_type, "🚗")
        embed = discord.Embed(
            title=f"{emoji} {interaction.user.display_name}'s Garage",
            description=f"**Body Type:** {user.body_type.value.title()}\n**Build:** {build.name}\n\n"
            + "\n".join(slot_lines),
            color=RARITY_COLORS.get(best_rarity, 0x3B82F6),
        )
        embed.add_field(name="Creds", value=str(user.currency), inline=True)
        embed.add_field(name="XP", value=str(user.xp), inline=True)

        await interaction.response.send_message(embed=embed)

        # Tutorial progression
        from bot.cogs.tutorial import advance_tutorial
        await advance_tutorial(interaction, str(interaction.user.id), "garage")

    @app_commands.command(name="equip", description="Equip a card to a build slot")
    @app_commands.describe(slot="The slot to equip into", card_name="Name of the card to equip")
    @app_commands.choices(slot=[
        app_commands.Choice(name=s.value.title(), value=s.value) for s in CardSlot
    ])
    async def equip(self, interaction: discord.Interaction, slot: str, card_name: str) -> None:
        from bot.cogs.cards import _parse_card_input

        parsed_name, parsed_serial = _parse_card_input(card_name)

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            # Find the card template
            card_result = await session.execute(select(Card).where(Card.name == parsed_name))
            card = card_result.scalar_one_or_none()
            if not card:
                await interaction.response.send_message(f"Card `{parsed_name}` not found.", ephemeral=True)
                return

            # Validate slot matches
            if card.slot.value != slot:
                await interaction.response.send_message(
                    f"`{card.name}` is a **{card.slot.value}** card and can't go in the **{slot}** slot.",
                    ephemeral=True,
                )
                return

            build_result = await session.execute(
                select(Build).where(Build.user_id == user.discord_id, Build.is_active == True)
            )
            build = build_result.scalar_one_or_none()
            if not build:
                await interaction.response.send_message("No active build found.", ephemeral=True)
                return

            # Get IDs of copies already equipped in other slots
            equipped_uc_ids = {
                uc_id for uc_id in build.slots.values() if uc_id is not None
            }

            # If a specific serial was requested, find that exact copy
            if parsed_serial is not None:
                uc_result = await session.execute(
                    select(UserCard).where(
                        UserCard.user_id == user.discord_id,
                        UserCard.card_id == card.id,
                        UserCard.serial_number == parsed_serial,
                    ).limit(1)
                )
                chosen = uc_result.scalar_one_or_none()
                if not chosen:
                    await interaction.response.send_message(
                        f"You don't own `{card.name}` #{parsed_serial}.", ephemeral=True
                    )
                    return
            else:
                # Find an available copy — prefer unequipped
                uc_result = await session.execute(
                    select(UserCard).where(
                        UserCard.user_id == user.discord_id,
                        UserCard.card_id == card.id,
                    ).order_by(UserCard.serial_number)
                )
                copies = list(uc_result.scalars().all())

                if not copies:
                    await interaction.response.send_message(
                        f"You don't own any copies of `{card.name}`.", ephemeral=True
                    )
                    return

                chosen = None
                for uc in copies:
                    if str(uc.id) not in equipped_uc_ids:
                        chosen = uc
                        break
                if chosen is None:
                    chosen = copies[0]

            # Equip the specific copy
            new_slots = dict(build.slots)
            new_slots[slot] = str(chosen.id)
            build.slots = new_slots
            await session.commit()

        await interaction.response.send_message(
            f"✅ Equipped **{card.name}** #{chosen.serial_number} in the **{slot.title()}** slot!"
        )

        # Tutorial progression
        from bot.cogs.tutorial import advance_tutorial
        await advance_tutorial(interaction, str(interaction.user.id), "equip")

    @equip.autocomplete("card_name")
    async def equip_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Show individual card copies the user owns, filtered by selected slot."""
        from bot.cogs.cards import _card_copy_autocomplete
        slot = interaction.namespace.slot
        return await _card_copy_autocomplete(interaction, current, slot_filter=slot)

    @app_commands.command(name="autoequip", description="Auto-equip your best or worst parts into every slot")
    @app_commands.describe(mode="Equip your best or worst parts")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Best (highest rarity)", value="best"),
        app_commands.Choice(name="Worst (lowest rarity)", value="worst"),
    ])
    async def autoequip(self, interaction: discord.Interaction, mode: str) -> None:
        use_best = mode == "best"

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            build_result = await session.execute(
                select(Build).where(Build.user_id == user.discord_id, Build.is_active == True)
            )
            build = build_result.scalar_one_or_none()
            if not build:
                await interaction.response.send_message("No active build found.", ephemeral=True)
                return

            # Load all user's cards with their Card relationship
            from sqlalchemy.orm import selectinload
            uc_result = await session.execute(
                select(UserCard)
                .where(UserCard.user_id == user.discord_id)
                .options(selectinload(UserCard.card))
            )
            all_copies = list(uc_result.scalars().all())

            # Group by slot
            by_slot: dict[str, list[UserCard]] = {}
            for uc in all_copies:
                slot_val = uc.card.slot.value
                by_slot.setdefault(slot_val, []).append(uc)

            # Sort each slot by rarity (desc for best, asc for worst), then by serial
            for slot_val, copies in by_slot.items():
                copies.sort(
                    key=lambda uc: (
                        RARITY_ORDER.get(uc.card.rarity.value, 0) * (-1 if use_best else 1),
                        uc.serial_number,
                    )
                )

            # Assign one card per slot, no card used twice
            new_slots = dict(build.slots)
            used_ids: set[str] = set()
            equipped_lines = []

            for slot in CardSlot:
                candidates = by_slot.get(slot.value, [])
                chosen = None
                for uc in candidates:
                    if str(uc.id) not in used_ids:
                        chosen = uc
                        break
                if chosen:
                    new_slots[slot.value] = str(chosen.id)
                    used_ids.add(str(chosen.id))
                    emoji = RARITY_EMOJI.get(chosen.card.rarity.value, "")
                    equipped_lines.append(
                        f"**{slot.value.title()}:** {emoji} {chosen.card.name} #{chosen.serial_number}"
                    )
                else:
                    new_slots[slot.value] = None
                    equipped_lines.append(f"**{slot.value.title()}:** — Empty —")

            build.slots = new_slots
            await session.commit()

        label = "best" if use_best else "worst"
        embed = discord.Embed(
            title=f"🔧 Auto-Equipped ({label.title()} Parts)",
            description="\n".join(equipped_lines),
            color=0x22C55E,
        )
        await interaction.response.send_message(embed=embed)

        # Tutorial progression (autoequip counts as equip)
        from bot.cogs.tutorial import advance_tutorial
        await advance_tutorial(interaction, str(interaction.user.id), "equip")

    @app_commands.command(name="peek", description="View another player's garage (public)")
    @app_commands.describe(target="The player whose garage to view")
    async def peek(self, interaction: discord.Interaction, target: discord.Member) -> None:
        async with async_session() as session:
            user = await session.get(User, str(target.id))
            if not user:
                await interaction.response.send_message(
                    f"{target.display_name} hasn't started playing yet.", ephemeral=True
                )
                return

            result = await session.execute(
                select(Build).where(Build.user_id == user.discord_id, Build.is_active == True)
            )
            build = result.scalar_one_or_none()
            if not build:
                await interaction.response.send_message(
                    f"{target.display_name} doesn't have a build yet.", ephemeral=True
                )
                return

            slot_lines = []
            best_rarity = "common"
            for slot in CardSlot:
                uc_id_str = build.slots.get(slot.value)
                if uc_id_str:
                    uc = await session.get(UserCard, uuid.UUID(uc_id_str))
                    if uc:
                        card = await session.get(Card, uc.card_id)
                        if card:
                            emoji = RARITY_EMOJI.get(card.rarity.value, "")
                            slot_lines.append(
                                f"**{slot.value.title()}:** {emoji} {card.name} #{uc.serial_number} ({card.rarity.value})"
                            )
                            if RARITY_ORDER.get(card.rarity.value, 0) > RARITY_ORDER.get(best_rarity, 0):
                                best_rarity = card.rarity.value
                            continue
                slot_lines.append(f"**{slot.value.title()}:** — Empty —")

        emoji = BODY_EMOJI.get(user.body_type, "🚗")
        embed = discord.Embed(
            title=f"{emoji} {target.display_name}'s Garage",
            description=f"**Body Type:** {user.body_type.value.title()}\n\n" + "\n".join(slot_lines),
            color=RARITY_COLORS.get(best_rarity, 0x3B82F6),
        )
        await interaction.response.send_message(embed=embed)

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
