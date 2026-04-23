"""Hangar cog — /start, /hangar, /equip, /build, /rig commands."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, update

from api.metrics import currency_spent, users_registered
from bot.sector_gating import get_active_sector
from config.logging import get_logger
from config.metrics import trace_exemplar
from config.tracing import traced_command
from db.models import (
    Build,
    Card,
    CardSlot,
    HullClass,
    RaceFormat,
    ShipRelease,
    ShipStatus,
    ShipTitle,
    TutorialStep,
    User,
    UserCard,
)
from db.session import async_session
from engine.card_mint import apply_stat_modifiers
from engine.class_engine import calculate_race_format, trending_toward
from engine.ship_namer import generate_ship_name
from engine.stat_resolver import aggregate_build

log = get_logger(__name__)

HULL_EMOJI = {
    HullClass.HAULER: "🚛",
    HullClass.SKIRMISHER: "⚔️",
    HullClass.SCOUT: "🔭",
}

RARITY_ORDER = {"common": 0, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4, "ghost": 5}
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

FORMAT_EMOJI = {
    RaceFormat.SPRINT: "🛣️",
    RaceFormat.ENDURANCE: "💨",
    RaceFormat.GAUNTLET: "🏁",
}

# Slots that define the ship's identity — locked once a title is minted
CORE_SLOTS = {CardSlot.REACTOR.value, CardSlot.HULL.value}


def _subclass_label(race_format: RaceFormat | None, hull_class: HullClass | None) -> str:
    """
    Format a human-readable subclass label combining format and hull class.
    e.g. "Gauntlet Scout", "Sprint Hauler", "Endurance Skirmisher".
    Falls back to just the hull class if no format is known yet.
    """
    hull_str = hull_class.value.title() if hull_class else "Unknown"
    if race_format:
        return f"{FORMAT_EMOJI.get(race_format, '')} {race_format.value.title()} {hull_str}"
    return f"{HULL_EMOJI.get(hull_class, '🚀')} {hull_str}"


async def _resolve_build(session, user_id: str, build_id: str | None = None) -> Build | None:
    """
    Resolve a build by its UUID string, or fall back to the default (is_active=True) build.
    Always scopes to the given user — returns None if not found or not owned.
    """
    if build_id:
        try:
            bid = uuid.UUID(build_id)
        except ValueError:
            return None
        result = await session.execute(
            select(Build).where(Build.id == bid, Build.user_id == user_id)
        )
    else:
        result = await session.execute(
            select(Build).where(Build.user_id == user_id, Build.is_active)
        )
    return result.scalar_one_or_none()


def _build_label(build: Build, title: ShipTitle | None = None) -> str:
    """Return a display label for a build, suitable for autocomplete choices."""
    if title:
        name = title.custom_name or title.auto_name
        fmt_emoji = FORMAT_EMOJI.get(title.race_format, "")
        hull_str = title.hull_class.value.title() if title.hull_class else ""
        label = f"{name} — {fmt_emoji} {title.race_format.value.title()} {hull_str}".strip()
    else:
        hc = build.hull_class
        hc_emoji = HULL_EMOJI.get(hc, "🚀")
        hull_str = hc.value.title() if hc else "Unknown"
        filled = sum(1 for v in build.slots.values() if v is not None)
        label = f"{build.name} · {hc_emoji} {hull_str} ({filled}/7)"
    if build.is_active:
        label += " ★"
    return label


async def _build_choices_for_user(session, user_id: str) -> list[tuple[str, str]]:
    """
    Return (display_label, build_uuid_str) for all of a user's builds.
    Default build first, then in insertion order.
    """
    result = await session.execute(
        select(Build).where(Build.user_id == user_id).order_by(Build.is_active.desc())
    )
    builds = list(result.scalars().all())
    choices = []
    for b in builds:
        title = await session.get(ShipTitle, b.ship_title_id) if b.ship_title_id else None
        choices.append((_build_label(b, title), str(b.id)))
    return choices


async def _build_name_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Module-level autocomplete handler for any 'build' parameter."""
    async with async_session() as session:
        choices = await _build_choices_for_user(session, str(interaction.user.id))
    return [
        app_commands.Choice(name=label[:100], value=build_id)
        for label, build_id in choices
        if current.lower() in label.lower()
    ][:25]


class HullClassSelect(discord.ui.View):
    """Button-based hull class selector for /start."""

    def __init__(self, user_id: int, username: str) -> None:
        super().__init__(timeout=60)
        self.user_id = user_id
        self.username = username
        self.chosen: HullClass | None = None

    async def _handle_choice(self, interaction: discord.Interaction, hull_class: HullClass) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your selection!", ephemeral=True)
            return

        self.chosen = hull_class
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
                hull_class=hull_class,
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
                hull_class=hull_class,
            )
            session.add(build)
            await session.commit()
            users_registered.inc()

        # ── TUTORIAL STORY BEGINS ──
        from bot.cogs.tutorial import _load_tutorial_data, grant_starter_cards, send_dialogue

        data = _load_tutorial_data()
        dialogue = data["dialogue"]
        uid = self.user_id  # int

        # Act 1: The Inheritance
        emoji = HULL_EMOJI.get(hull_class, "🚀")
        embed = discord.Embed(
            title=f"{emoji} Welcome to Dare2Drive!",
            description=f"**Hull Class:** {hull_class.value.title()}",
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

        # Act 3: The Scrapyard
        view = await send_dialogue(
            interaction,
            dialogue["junkyard"],
            title="🔩 The Scrapyard",
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

    @discord.ui.button(label="🚛 Hauler", style=discord.ButtonStyle.danger)
    async def hauler_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_choice(interaction, HullClass.HAULER)

    @discord.ui.button(label="⚔️ Skirmisher", style=discord.ButtonStyle.primary)
    async def skirmisher_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._handle_choice(interaction, HullClass.SKIRMISHER)

    @discord.ui.button(label="🔭 Scout", style=discord.ButtonStyle.secondary)
    async def scout_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_choice(interaction, HullClass.SCOUT)


class HangarCog(commands.Cog):
    """Hangar management — hull selection, build viewing, equipping."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="start", description="Create your Dare2Drive account and pick a hull class"
    )
    @traced_command
    async def start(self, interaction: discord.Interaction) -> None:
        # Guard against already-acknowledged interactions
        if interaction.response.is_done():
            return

        async with async_session() as session:
            existing = await session.get(User, str(interaction.user.id))
            if existing:
                await interaction.response.send_message(
                    "You already have an account!", ephemeral=True
                )
                return

            sector = await get_active_sector(interaction, session)

        sector_label = sector.name if sector else "the outer rim"
        opening_line = (
            f"You've drifted into **{sector_label}**. "
            "Sketchy Dave runs the strip here — he'll show you the ropes."
        )

        view = HullClassSelect(interaction.user.id, interaction.user.display_name)
        embed = discord.Embed(
            title="🏁 Choose Your Hull Class",
            description=(
                f"{opening_line}\n\n"
                "Pick your ship's frame. This is permanent and cosmetic only.\n\n"
                "🚛 **Hauler** — Built tough, takes a beating\n"
                "⚔️ **Skirmisher** — Fast and aggressive\n"
                "🔭 **Scout** — Light, nimble, hard to catch"
            ),
            color=0xF59E0B,
        )

        # Double-check before sending (race condition safety)
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="hangar", description="View your current build")
    @app_commands.describe(build="Which build to view (default: your default build)")
    @app_commands.autocomplete(build=_build_name_autocomplete)
    @traced_command
    async def hangar(self, interaction: discord.Interaction, build: str | None = None) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            b = await _resolve_build(session, user.discord_id, build_id=build)
            if not b:
                await interaction.response.send_message(
                    "Build not found. Use `/build list` to see your builds.", ephemeral=True
                )
                return

            # Resolve card names for each slot (slots now store user_card_id)
            slot_lines = []
            best_rarity = "common"
            for slot in CardSlot:
                uc_id_str = b.slots.get(slot.value)
                if uc_id_str:
                    uc = await session.get(UserCard, uuid.UUID(uc_id_str))
                    if uc:
                        card = await session.get(Card, uc.card_id)
                        if card:
                            r_emoji = RARITY_EMOJI.get(card.rarity.value, "")
                            slot_lines.append(
                                f"**{slot.value.title()}:** {r_emoji} {card.name} #{uc.serial_number} ({card.rarity.value})"  # noqa: E501
                            )
                            if RARITY_ORDER.get(card.rarity.value, 0) > RARITY_ORDER.get(
                                best_rarity, 0
                            ):
                                best_rarity = card.rarity.value
                        else:
                            slot_lines.append(f"**{slot.value.title()}:** ❌ Card not found")
                    else:
                        slot_lines.append(f"**{slot.value.title()}:** ❌ Part missing (wrecked?)")
                else:
                    slot_lines.append(f"**{slot.value.title()}:** — Empty —")

            # Load title info if one is minted
            title = None
            if b.ship_title_id:
                title = await session.get(ShipTitle, b.ship_title_id)

        build_hc = b.hull_class or user.hull_class
        race_format = title.race_format if title else None
        subclass = _subclass_label(race_format, build_hc)

        if title:
            display_name = title.custom_name or title.auto_name
            release_str = f"{title.release_serial:03d}"
            header = f'**"{display_name}"** · #{release_str}\n**Type:** {subclass}'
        else:
            filled = sum(1 for v in b.slots.values() if v is not None)
            header = f"**Type:** {subclass}\n**Slots:** {filled}/7 filled"

        embed = discord.Embed(
            title=f"🔧 {interaction.user.display_name}'s Hangar",
            description=f"{header}\n\n" + "\n".join(slot_lines),
            color=RARITY_COLORS.get(best_rarity, 0x3B82F6),
        )
        embed.add_field(name="Creds", value=str(user.currency), inline=True)
        embed.add_field(name="XP", value=str(user.xp), inline=True)
        if title:
            embed.set_footer(text="🔒 Core parts locked · /build disassemble to rebuild")

        await interaction.response.send_message(embed=embed)

        # Tutorial progression — internal step name is "garage"
        from bot.cogs.tutorial import advance_tutorial

        await advance_tutorial(interaction, str(interaction.user.id), "garage")

    @app_commands.command(name="equip", description="Equip a card to a build slot")
    @app_commands.describe(
        slot="The slot to equip into",
        card_name="Name of the card to equip",
        build="Which build to equip into (default: your default build)",
    )
    @app_commands.choices(
        slot=[app_commands.Choice(name=s.value.title(), value=s.value) for s in CardSlot]
    )
    @app_commands.autocomplete(build=_build_name_autocomplete)
    @traced_command
    async def equip(
        self,
        interaction: discord.Interaction,
        slot: str,
        card_name: str,
        build: str | None = None,
    ) -> None:
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
                await interaction.response.send_message(
                    f"Card `{parsed_name}` not found.", ephemeral=True
                )
                return

            # Validate slot matches
            if card.slot.value != slot:
                await interaction.response.send_message(
                    f"`{card.name}` is a **{card.slot.value}** card and can't go in the **{slot}** slot.",  # noqa: E501
                    ephemeral=True,
                )
                return

            b = await _resolve_build(session, user.discord_id, build_id=build)
            if not b:
                await interaction.response.send_message(
                    "Build not found. Use `/build list` to see your builds.", ephemeral=True
                )
                return

            # Check hull class compatibility
            build_hc = b.hull_class or user.hull_class
            if card.compatible_hull_classes is not None:
                if build_hc and build_hc.value not in card.compatible_hull_classes:
                    compat_str = ", ".join(t.title() for t in card.compatible_hull_classes)
                    await interaction.response.send_message(
                        f"⚠️ **{card.name}** only fits **{compat_str}** ships. "
                        f"Your ship is **{build_hc.value.title()}**.",
                        ephemeral=True,
                    )
                    return

            # Core-lock check — can't swap reactor or hull while a title is active
            if b.core_locked and slot in CORE_SLOTS:
                await interaction.response.send_message(
                    f"🔒 Your ship has a Ship Title. You can't replace the **{slot.title()}** "
                    f"without disassembling first (`/build disassemble`).",
                    ephemeral=True,
                )
                return

            # Get IDs of copies already equipped in other slots
            equipped_uc_ids = {uc_id for uc_id in b.slots.values() if uc_id is not None}

            # If a specific serial was requested, find that exact copy
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
                # Find an available copy — prefer unequipped
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

            # If a title is active and this is a wear slot, log the swap
            old_card_name: str | None = None
            if b.core_locked and b.ship_title_id:
                old_uc_id = b.slots.get(slot)
                if old_uc_id:
                    old_uc = await session.get(UserCard, uuid.UUID(old_uc_id))
                    if old_uc:
                        old_card_obj = await session.get(Card, old_uc.card_id)
                        old_card_name = old_card_obj.name if old_card_obj else None

            # Equip the specific copy
            new_slots = dict(b.slots)
            new_slots[slot] = str(chosen.id)
            b.slots = new_slots

            # Append to part_swap_log on the active title
            if b.core_locked and b.ship_title_id:
                title = await session.get(ShipTitle, b.ship_title_id)
                if title:
                    swap_log = list(title.part_swap_log or [])
                    swap_log.append(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "slot": slot,
                            "old_card_name": old_card_name,
                            "new_card_name": card.name,
                        }
                    )
                    title.part_swap_log = swap_log

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

    @app_commands.command(
        name="autoequip", description="Auto-equip your best or worst parts into every slot"
    )
    @app_commands.describe(
        mode="Equip your best or worst parts",
        build="Which build to equip into (default: your default build)",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Best (highest rarity)", value="best"),
            app_commands.Choice(name="Worst (lowest rarity)", value="worst"),
        ]
    )
    @app_commands.autocomplete(build=_build_name_autocomplete)
    @traced_command
    async def autoequip(
        self, interaction: discord.Interaction, mode: str, build: str | None = None
    ) -> None:
        use_best = mode == "best"

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            b = await _resolve_build(session, user.discord_id, build_id=build)
            if not b:
                await interaction.response.send_message(
                    "Build not found. Use `/build list` to see your builds.", ephemeral=True
                )
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
            old_slots = dict(b.slots)
            new_slots = dict(b.slots)
            used_ids: set[str] = set()
            equipped_lines = []
            chosen_by_slot: dict[str, UserCard | None] = {}

            for slot in CardSlot:
                candidates = by_slot.get(slot.value, [])
                chosen = None
                for uc in candidates:
                    if str(uc.id) not in used_ids:
                        chosen = uc
                        break
                chosen_by_slot[slot.value] = chosen
                if chosen:
                    new_slots[slot.value] = str(chosen.id)
                    used_ids.add(str(chosen.id))
                    emoji = RARITY_EMOJI.get(chosen.card.rarity.value, "")
                    equipped_lines.append(
                        f"**{slot.value.title()}:** {emoji} {chosen.card.name} #{chosen.serial_number}"  # noqa: E501
                    )
                else:
                    new_slots[slot.value] = None
                    equipped_lines.append(f"**{slot.value.title()}:** — Empty —")

            b.slots = new_slots

            # Log part swaps to the title if minted
            if b.core_locked and b.ship_title_id:
                title = await session.get(ShipTitle, b.ship_title_id)
                if title:
                    ts = datetime.now(timezone.utc).isoformat()
                    swap_log = list(title.part_swap_log or [])
                    for slot_val in CardSlot:
                        sn = slot_val.value
                        if old_slots.get(sn) == new_slots.get(sn):
                            continue
                        old_uc_id = old_slots.get(sn)
                        old_name = None
                        if old_uc_id:
                            old_uc = await session.get(UserCard, uuid.UUID(old_uc_id))
                            if old_uc:
                                old_card_obj = await session.get(Card, old_uc.card_id)
                                old_name = old_card_obj.name if old_card_obj else None
                        new_uc = chosen_by_slot.get(sn)
                        swap_log.append(
                            {
                                "timestamp": ts,
                                "slot": sn,
                                "old_card_name": old_name,
                                "new_card_name": new_uc.card.name if new_uc else None,
                            }
                        )
                    title.part_swap_log = swap_log

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

    @app_commands.command(name="peek", description="View another player's hangar (public)")
    @app_commands.describe(target="The player whose hangar to view")
    @traced_command
    async def peek(self, interaction: discord.Interaction, target: discord.Member) -> None:
        async with async_session() as session:
            user = await session.get(User, str(target.id))
            if not user:
                await interaction.response.send_message(
                    f"{target.display_name} hasn't started playing yet.", ephemeral=True
                )
                return

            result = await session.execute(
                select(Build).where(Build.user_id == user.discord_id, Build.is_active)
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
                                f"**{slot.value.title()}:** {emoji} {card.name} #{uc.serial_number} ({card.rarity.value})"  # noqa: E501
                            )
                            if RARITY_ORDER.get(card.rarity.value, 0) > RARITY_ORDER.get(
                                best_rarity, 0
                            ):
                                best_rarity = card.rarity.value
                            continue
                slot_lines.append(f"**{slot.value.title()}:** — Empty —")

        emoji = HULL_EMOJI.get(user.hull_class, "🚀")
        embed = discord.Embed(
            title=f"{emoji} {target.display_name}'s Hangar",
            description=f"**Hull Class:** {user.hull_class.value.title()}\n\n"
            + "\n".join(slot_lines),
            color=RARITY_COLORS.get(best_rarity, 0x3B82F6),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="profile", description="View your profile")
    @traced_command
    async def profile(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

        emoji = HULL_EMOJI.get(user.hull_class, "🚀")
        embed = discord.Embed(
            title=f"{emoji} {user.username}",
            color=0x3B82F6,
        )
        embed.add_field(name="Hull Class", value=user.hull_class.value.title(), inline=True)
        embed.add_field(name="Creds", value=str(user.currency), inline=True)
        embed.add_field(name="XP", value=str(user.xp), inline=True)
        embed.set_footer(
            text=f"Member since {user.created_at.strftime('%Y-%m-%d') if user.created_at else 'unknown'}"  # noqa: E501
        )
        await interaction.response.send_message(embed=embed)

    # ── /build subcommands ─────────────────────────────────────────────────────

    build_group = app_commands.Group(name="build", description="Manage your ship build")

    @build_group.command(name="preview", description="Preview your build's format and stats")
    @app_commands.describe(build="Which build to preview (default: your default build)")
    @app_commands.autocomplete(build=_build_name_autocomplete)
    @traced_command
    async def build_preview(
        self, interaction: discord.Interaction, build: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.followup.send("Use `/start` first!", ephemeral=True)
                return

            b = await _resolve_build(session, user.discord_id, build_id=build)
            if not b:
                await interaction.followup.send(
                    "Build not found. Use `/build list` to see your builds.", ephemeral=True
                )
                return

            # Load cards for stat resolution
            cards: dict = {}
            for slot in CardSlot:
                uc_id_str = b.slots.get(slot.value)
                if not uc_id_str:
                    continue
                uc = await session.get(UserCard, uuid.UUID(uc_id_str))
                if not uc:
                    continue
                card = await session.get(Card, uc.card_id)
                if not card:
                    continue
                effective_stats = apply_stat_modifiers(card.stats, uc.stat_modifiers or {})
                cards[uc_id_str] = {"slot": card.slot.value, "stats": effective_stats}

            hull_class = b.hull_class or user.hull_class
            stats = aggregate_build(
                b.slots, cards, body_type=hull_class.value if hull_class else None
            )

            filled = sum(1 for v in b.slots.values() if v is not None)
            all_filled = filled == len(CardSlot)

            trending = trending_toward(stats, hull_class)

            def bar(pct: float, width: int = 10) -> str:
                filled_blocks = round(pct * width)
                return "█" * filled_blocks + "░" * (width - filled_blocks)

            lines = []
            for race_format, pct in trending[:5]:
                fmt_emoji = FORMAT_EMOJI.get(race_format, "")
                pct_display = f"{int(pct * 100)}%"
                lines.append(
                    f"{fmt_emoji} **{race_format.value.upper()}** {bar(pct)} {pct_display}"
                )

            if all_filled:
                actual_format = calculate_race_format(stats, hull_class)
                subclass = _subclass_label(actual_format, hull_class)
                desc = f"**Type:** {subclass}\n\n"
            else:
                subclass = _subclass_label(None, hull_class)
                desc = (
                    f"**Type:** {subclass} *(format assigned at mint)*\n"
                    f"**Slots filled:** {filled}/7\n\n"
                )

            desc += "\n".join(lines)

            lock_str = "🔒 Minted" if b.core_locked else "🔧 In Progress"
            embed = discord.Embed(
                title=f"{lock_str} · Build Preview",
                description=desc,
                color=0x3B82F6,
            )
            if not b.core_locked:
                embed.set_footer(
                    text="Use /build mint to lock in your format and mint a Ship Title"
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

        # Tutorial progression
        from bot.cogs.tutorial import advance_tutorial

        await advance_tutorial(interaction, str(interaction.user.id), "build_preview")

    @build_group.command(name="mint", description="Mint a Ship Title for your completed build")
    @app_commands.describe(build="Which build to mint (default: your default build)")
    @app_commands.autocomplete(build=_build_name_autocomplete)
    @traced_command
    async def build_mint(self, interaction: discord.Interaction, build: str | None = None) -> None:
        await interaction.response.defer(ephemeral=True)

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.followup.send("Use `/start` first!", ephemeral=True)
                return

            b = await _resolve_build(session, user.discord_id, build_id=build)
            if not b:
                await interaction.followup.send(
                    "Build not found. Use `/build list` to see your builds.", ephemeral=True
                )
                return

            if b.core_locked:
                await interaction.followup.send(
                    "Your build already has a Ship Title. "
                    "Use `/build disassemble` first to rebuild.",
                    ephemeral=True,
                )
                return

            # All 7 slots must be filled
            missing = [s.value for s in CardSlot if not b.slots.get(s.value)]
            if missing:
                missing_str = ", ".join(s.title() for s in missing)
                await interaction.followup.send(
                    f"❌ Fill all 7 slots before minting. Missing: **{missing_str}**",
                    ephemeral=True,
                )
                return

            # Load cards for stats + snapshot
            cards: dict = {}
            snapshot: dict = {}
            for slot in CardSlot:
                uc_id_str = b.slots[slot.value]
                uc = await session.get(UserCard, uuid.UUID(uc_id_str))
                if not uc:
                    await interaction.followup.send(
                        f"❌ Missing part in **{slot.value}** slot (wrecked?). "
                        "Re-equip before minting.",
                        ephemeral=True,
                    )
                    return
                card = await session.get(Card, uc.card_id)
                if not card:
                    await interaction.followup.send(
                        f"❌ Card data missing for **{slot.value}** slot.", ephemeral=True
                    )
                    return
                effective_stats = apply_stat_modifiers(card.stats, uc.stat_modifiers or {})
                cards[uc_id_str] = {"slot": card.slot.value, "stats": effective_stats}
                snapshot[slot.value] = {
                    "card_id": str(card.id),
                    "user_card_id": uc_id_str,
                    "serial": uc.serial_number,
                    "name": card.name,
                    "rarity": card.rarity.value,
                }

            hull_class = b.hull_class or user.hull_class
            stats = aggregate_build(
                b.slots, cards, body_type=hull_class.value if hull_class else None
            )
            race_format = calculate_race_format(stats, hull_class)
            auto_name = generate_ship_name(race_format, hull_class, stats)

            # Get the active release and atomically increment its serial
            release_result = await session.execute(
                select(ShipRelease)
                .where(ShipRelease.ended_at.is_(None))
                .order_by(ShipRelease.started_at)
                .limit(1)
                .with_for_update()
            )
            release = release_result.scalar_one_or_none()
            if not release:
                await interaction.followup.send(
                    "❌ No active release found. Contact an admin.", ephemeral=True
                )
                return

            release.serial_counter += 1
            serial = release.serial_counter

            title = ShipTitle(
                id=uuid.uuid4(),
                release_id=release.id,
                release_serial=serial,
                owner_id=user.discord_id,
                build_id=b.id,
                hull_class=hull_class,
                race_format=race_format,
                status=ShipStatus.ACTIVE,
                auto_name=auto_name,
                custom_name=None,
                build_snapshot=snapshot,
                pedigree_bonus=0.0,
                ownership_log=[
                    {
                        "owner_id": user.discord_id,
                        "acquired_at": datetime.now(timezone.utc).isoformat(),
                        "transferred_at": None,
                    }
                ],
                part_swap_log=[],
                race_record={"wins": 0, "losses": 0},
            )
            session.add(title)
            await session.flush()  # get title.id before updating build

            b.core_locked = True
            b.ship_title_id = title.id
            await session.commit()

        fmt_emoji = FORMAT_EMOJI.get(race_format, "")
        hull_str = hull_class.value.title() if hull_class else "Unknown"
        embed = discord.Embed(
            title="🏆 Ship Title Minted!",
            description=(
                f'**"{auto_name}"**\n'
                f"{release.name} #{serial:03d}\n\n"
                f"{fmt_emoji} Format: **{race_format.value.upper()}**\n"
                f"Hull: **{hull_str}**"
            ),
            color=0xF59E0B,
        )
        slot_lines = [
            f"**{slot.title()}:** {data['name']} (#{data['serial']})"
            for slot, data in snapshot.items()
        ]
        embed.add_field(name="Build", value="\n".join(slot_lines), inline=False)
        embed.set_footer(
            text="Wear parts (thrusters, retros, etc.) can still be swapped. "
            "Core parts (reactor, hull) are locked."
        )
        await interaction.followup.send(embed=embed)

        # Tutorial progression
        from bot.cogs.tutorial import advance_tutorial

        await advance_tutorial(interaction, str(interaction.user.id), "build_mint")

    @build_group.command(
        name="disassemble", description="Scrap your Ship Title and unlock your build"
    )
    @app_commands.describe(build="Which build to disassemble (default: your default build)")
    @app_commands.autocomplete(build=_build_name_autocomplete)
    @traced_command
    async def build_disassemble(
        self, interaction: discord.Interaction, build: str | None = None
    ) -> None:
        build_id_after_confirm: uuid.UUID | None = None

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            b = await _resolve_build(session, user.discord_id, build_id=build)
            if not b or not b.core_locked or not b.ship_title_id:
                await interaction.response.send_message(
                    "That build doesn't have a Ship Title to disassemble.", ephemeral=True
                )
                return

            title = await session.get(ShipTitle, b.ship_title_id)
            if not title:
                await interaction.response.send_message("Ship Title not found.", ephemeral=True)
                return

            build_id_after_confirm = b.id
            was_default = b.is_active

        title_display = title.custom_name or title.auto_name
        serial_str = f"#{title.release_serial:03d}"

        view = _ConfirmView(interaction.user.id)
        default_warning = (
            "\n\n⚠️ This is your default build — use `/build set-default` afterwards."
            if was_default
            else ""
        )
        embed = discord.Embed(
            title="⚠️ Disassemble Ship?",
            description=(
                f'This will permanently scrap **"{title_display}"** {serial_str}.\n\n'
                "The title's history is preserved but it can no longer be raced.\n"
                f"All parts stay in your inventory.{default_warning}"
            ),
            color=0xEF4444,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            await interaction.edit_original_response(
                content="Disassembly cancelled.", embed=None, view=None
            )
            return

        async with async_session() as session:
            b = await session.get(Build, build_id_after_confirm)
            title = await session.get(ShipTitle, b.ship_title_id)
            if b and title:
                title.status = ShipStatus.SCRAPPED
                title.build_id = None
                b.core_locked = False
                b.ship_title_id = None
                await session.commit()

        await interaction.edit_original_response(
            content=f'✅ **"{title_display}"** {serial_str} has been scrapped. Parts unlocked.',
            embed=None,
            view=None,
        )

    @build_group.command(name="new", description="Open a new build slot (500 Creds)")
    @app_commands.describe(hull_class="Hull class for the new build")
    @app_commands.choices(
        hull_class=[
            app_commands.Choice(name="🚛 Hauler", value="hauler"),
            app_commands.Choice(name="⚔️ Skirmisher", value="skirmisher"),
            app_commands.Choice(name="🔭 Scout", value="scout"),
        ]
    )
    @traced_command
    async def build_new(self, interaction: discord.Interaction, hull_class: str) -> None:
        from bot.cogs.tutorial import is_tutorial_complete

        BUILD_SLOT_COST = 500

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            if not is_tutorial_complete(user):
                await interaction.response.send_message(
                    "Finish the tutorial before managing multiple builds.", ephemeral=True
                )
                return

            if user.currency < BUILD_SLOT_COST:
                await interaction.response.send_message(
                    f"You need **{BUILD_SLOT_COST} Creds** to open a new build slot. "
                    f"You have **{user.currency}**.",
                    ephemeral=True,
                )
                return

            hc = HullClass(hull_class)

            # Deactivate current default, deduct cost, create new build
            user.currency -= BUILD_SLOT_COST
            currency_spent.labels(reason="build_slot").inc(
                BUILD_SLOT_COST, exemplar=trace_exemplar()
            )
            await session.execute(
                update(Build).where(Build.user_id == user.discord_id).values(is_active=False)
            )
            new_build = Build(
                user_id=user.discord_id,
                name="New Build",
                slots={slot.value: None for slot in CardSlot},
                is_active=True,
                hull_class=hc,
            )
            session.add(new_build)
            await session.commit()

        hc_emoji = HULL_EMOJI.get(hc, "🚀")
        await interaction.response.send_message(
            f"✅ New **{hc_emoji} {hc.value.title()}** build created and set as default.\n"
            f"Use `/equip` or `/autoequip` to fill it. **−{BUILD_SLOT_COST} Creds**",
            ephemeral=True,
        )

    @build_group.command(name="list", description="List all your builds")
    @traced_command
    async def build_list(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            result = await session.execute(
                select(Build)
                .where(Build.user_id == user.discord_id)
                .order_by(Build.is_active.desc())
            )
            builds = list(result.scalars().all())

            lines = []
            for b in builds:
                title = await session.get(ShipTitle, b.ship_title_id) if b.ship_title_id else None
                hc = b.hull_class
                hc_emoji = HULL_EMOJI.get(hc, "🚀")
                default_marker = " ★ **default**" if b.is_active else ""

                if title:
                    display_name = title.custom_name or title.auto_name
                    subclass = _subclass_label(title.race_format, title.hull_class)
                    serial = f"#{title.release_serial:03d}"
                    lines.append(
                        f"{hc_emoji} **{display_name}** {serial} · {subclass}{default_marker}"
                    )
                else:
                    filled = sum(1 for v in b.slots.values() if v is not None)
                    subclass = _subclass_label(None, hc)
                    lines.append(
                        f"{hc_emoji} **{b.name}** · {subclass} ({filled}/7){default_marker}"
                    )

        embed = discord.Embed(
            title="🔧 Your Builds",
            description="\n".join(lines) or "No builds found.",
            color=0x3B82F6,
        )
        embed.set_footer(text="/build set-default to switch · /build new to add a slot (500 Creds)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @build_group.command(name="set-default", description="Set a build as your default")
    @app_commands.describe(build="The build to set as default")
    @app_commands.autocomplete(build=_build_name_autocomplete)
    @traced_command
    async def build_set_default(self, interaction: discord.Interaction, build: str) -> None:
        try:
            build_uuid = uuid.UUID(build)
        except ValueError:
            await interaction.response.send_message("Invalid build selection.", ephemeral=True)
            return

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            result = await session.execute(
                select(Build).where(Build.id == build_uuid, Build.user_id == user.discord_id)
            )
            target = result.scalar_one_or_none()
            if not target:
                await interaction.response.send_message("Build not found.", ephemeral=True)
                return

            if target.is_active:
                await interaction.response.send_message(
                    "That's already your default build.", ephemeral=True
                )
                return

            # Get display name before committing
            title = (
                await session.get(ShipTitle, target.ship_title_id) if target.ship_title_id else None
            )
            display_name = (title.custom_name or title.auto_name) if title else target.name

            await session.execute(
                update(Build).where(Build.user_id == user.discord_id).values(is_active=False)
            )
            target.is_active = True
            await session.commit()

        await interaction.response.send_message(
            f"✅ **{display_name}** is now your default build.", ephemeral=True
        )

    # ── /rig subcommands ───────────────────────────────────────────────────────

    rig_group = app_commands.Group(name="rig", description="Manage your Ship Title")

    @rig_group.command(name="rename", description="Set a custom name for your Ship Title")
    @app_commands.describe(
        name="Your custom name (max 50 characters)",
        build="Which build's title to rename (default: your default build)",
    )
    @app_commands.autocomplete(build=_build_name_autocomplete)
    @traced_command
    async def rig_rename(
        self, interaction: discord.Interaction, name: str, build: str | None = None
    ) -> None:
        if len(name) > 50:
            await interaction.response.send_message(
                "Name must be 50 characters or fewer.", ephemeral=True
            )
            return

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            b = await _resolve_build(session, user.discord_id, build_id=build)
            if not b or not b.core_locked or not b.ship_title_id:
                await interaction.response.send_message(
                    "That build doesn't have a Ship Title to rename. Mint one with `/build mint`.",
                    ephemeral=True,
                )
                return

            title = await session.get(ShipTitle, b.ship_title_id)
            if not title:
                await interaction.response.send_message("Ship Title not found.", ephemeral=True)
                return

            old_name = title.custom_name or title.auto_name
            title.custom_name = name
            await session.commit()

        await interaction.response.send_message(
            f'✅ Renamed **"{old_name}"** → **"{name}"**', ephemeral=True
        )


class _ConfirmView(discord.ui.View):
    """Simple two-button confirmation."""

    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=30)
        self.user_id = user_id
        self.confirmed = False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_btn(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your action!", ephemeral=True)
            return
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your action!", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HangarCog(bot))
