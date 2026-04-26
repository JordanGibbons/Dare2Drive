"""Tutorial cog — guided onboarding flow for new players."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.metrics import users_registered
from config.logging import get_logger
from config.tracing import traced_command
from db.models import Card, TutorialStep, User, UserCard
from db.session import async_session

log = get_logger(__name__)

_TUTORIAL_DATA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "tutorial.json"

# Which commands are allowed at each tutorial step. Keyed by the slash
# command's qualified_name (i.e. full path including any parent Group),
# so e.g. "build preview" matches /build preview but NOT /research preview.
# Anything not listed is blocked until COMPLETE.
STEP_ALLOWED_COMMANDS: dict[TutorialStep, set[str]] = {
    TutorialStep.STARTED: set(),
    TutorialStep.INVENTORY: {"inventory"},
    TutorialStep.INSPECT: {"inventory", "inspect"},
    TutorialStep.EQUIP: {"inventory", "inspect", "equip", "autoequip"},
    TutorialStep.MINT: {
        "inventory",
        "inspect",
        "equip",
        "autoequip",
        "build preview",
        "build mint",
    },
    TutorialStep.GARAGE: {"inventory", "inspect", "equip", "autoequip", "hangar"},
    TutorialStep.RACE: {"inventory", "inspect", "equip", "autoequip", "hangar", "race"},
    TutorialStep.PACK: {"inventory", "inspect", "equip", "autoequip", "hangar"},
    TutorialStep.COMPLETE: set(),  # Empty means all commands allowed
}

# Commands that are always allowed regardless of tutorial step (qualified names).
ALWAYS_ALLOWED = {
    "start",
    "profile",
    "admin_reset_player",
    "admin_set_tutorial_step",
    "admin_give_creds",
    "skip_tutorial",
}


def _load_tutorial_data() -> dict[str, Any]:
    with open(_TUTORIAL_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def is_tutorial_complete(user: User) -> bool:
    """Check if user has finished the tutorial."""
    return user.tutorial_step == TutorialStep.COMPLETE


def is_command_allowed(user: User, command_name: str) -> bool:
    """Check if a command is allowed at the user's current tutorial step."""
    if is_tutorial_complete(user):
        return True
    if command_name in ALWAYS_ALLOWED:
        return True
    allowed = STEP_ALLOWED_COMMANDS.get(user.tutorial_step, set())
    return command_name in allowed


def get_blocked_message(user: User, command_name: str) -> str:
    """Get a snarky message explaining why a command is blocked."""
    step = user.tutorial_step
    step_hints = {
        TutorialStep.STARTED: "Hold on, your story's still unfolding. Sit tight.",
        TutorialStep.INVENTORY: "Easy there. Use `/inventory` first — gotta know what you've got before you do anything with it.",  # noqa: E501
        TutorialStep.INSPECT: "You've got parts but haven't looked at them. Try `/inspect` on one of your cards first.",  # noqa: E501
        TutorialStep.EQUIP: "Parts on the floor don't make the ship fly. Use `/equip` or `/autoequip best` to install them.",  # noqa: E501
        TutorialStep.MINT: "All slots filled — use `/build preview` to see your format, then `/build mint` to lock it in.",  # noqa: E501
        TutorialStep.GARAGE: "Your ship's minted. Use `/hangar` to look it over, then head out for a run.",  # noqa: E501
        TutorialStep.RACE: "Your ship's ready. Stop stalling and use `/race` already.",
        TutorialStep.PACK: "You've got a salvage crate to open. Patience.",
    }
    return step_hints.get(
        step, f"You can't use `/{command_name}` yet. Keep following the tutorial."
    )


class ContinueView(discord.ui.View):
    """A single 'Continue' button that resolves an asyncio Event when clicked."""

    def __init__(self, user_id: int, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self._event = asyncio.Event()

    @discord.ui.button(label="Continue ▶", style=discord.ButtonStyle.primary)
    async def continue_btn(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:  # noqa: E501
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your tutorial.", ephemeral=True)
            return
        await interaction.response.defer()
        self._event.set()
        self.stop()

    async def wait_for_click(self) -> None:
        """Await until the player clicks Continue (or timeout)."""
        await self._event.wait()


async def send_dialogue(
    destination: discord.abc.Messageable | discord.Interaction,
    lines: list[str],
    color: int = 0xF59E0B,
    title: str | None = None,
    with_continue: bool = False,
    user_id: int | None = None,
) -> ContinueView | None:
    """
    Send dialogue lines as a single embed.
    If with_continue=True, attaches a Continue button and returns the view.
    Caller should await view.wait_for_click() before sending the next beat.
    """
    text = "\n\n".join(f"*{line}*" for line in lines)
    embed = discord.Embed(description=text, color=color)
    if title:
        embed.title = title

    view = ContinueView(user_id) if (with_continue and user_id) else None

    kwargs: dict = {"embed": embed, "ephemeral": True}
    if view is not None:
        kwargs["view"] = view

    if isinstance(destination, discord.Interaction):
        if destination.response.is_done():
            await destination.followup.send(**kwargs)
        else:
            await destination.response.send_message(**kwargs)
    else:
        # Non-interaction fallback — ephemeral not supported outside interactions
        await destination.send(embed=embed, view=view)

    return view


async def grant_starter_cards(session: AsyncSession, user: User) -> list[Card]:
    """Grant temporary tutorial cards to a new player (serial_number=0, no real minting)."""
    from engine.card_mint import mint_tutorial_card

    data = _load_tutorial_data()
    starter_names = data["starter_cards"]
    granted: list[Card] = []

    for name in starter_names:
        result = await session.execute(select(Card).where(Card.name == name))
        card = result.scalar_one_or_none()
        if not card:
            log.warning("Starter card not found in DB: %s", name)
            continue

        await mint_tutorial_card(session, user.discord_id, card)
        granted.append(card)

    return granted


def build_npc_race_data() -> dict[str, Any]:
    """Build the NPC opponent's race data dict for compute_race."""
    data = _load_tutorial_data()
    npc = data["npc_opponent"]

    # Build slots and cards dicts in the format compute_race expects
    slots: dict[str, str | None] = {
        "reactor": "npc_reactor",
        "drive": "npc_drive",
        "thrusters": "npc_thrusters",
        "stabilizers": "npc_stabilizers",
        "hull": "npc_hull",
        "overdrive": "npc_overdrive",
        "retros": "npc_retros",
    }
    cards: dict[str, dict[str, Any]] = {}
    for slot_name, card_data in npc["cards"].items():
        fake_id = f"npc_{slot_name}"
        cards[fake_id] = {
            "id": fake_id,
            "name": card_data["name"],
            "slot": slot_name,
            "rarity": "common",
            "stats": card_data["stats"],
        }

    return {
        "user_id": npc["user_id"],
        "slots": slots,
        "cards": cards,
    }


async def advance_tutorial(
    interaction: discord.Interaction,
    user_id: str,
    command_name: str,
    **kwargs: Any,
) -> None:
    """
    Called AFTER a command completes to advance the tutorial.
    This is the post-command hook that progresses the story.
    """
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user or is_tutorial_complete(user):
            return

        data = _load_tutorial_data()
        dialogue = data["dialogue"]
        step = user.tutorial_step

        if step == TutorialStep.INVENTORY and command_name == "inventory":
            # They checked inventory — teach inspect
            # Pick the first starter card name for the hint
            starter_cards = data["starter_cards"]
            card_name = starter_cards[0] if starter_cards else "your card"
            lines = [line.replace("{card_name}", card_name) for line in dialogue["teach_inspect"]]
            user.tutorial_step = TutorialStep.INSPECT
            await session.commit()
            await send_dialogue(interaction, lines, title="🔍 Check Your Parts")

        elif step == TutorialStep.INSPECT and command_name == "inspect":
            # They inspected a card — teach equip
            starter_cards = data["starter_cards"]
            engine_card = starter_cards[0] if starter_cards else "your reactor"
            lines = [line.replace("{engine_card}", engine_card) for line in dialogue["teach_equip"]]
            user.tutorial_step = TutorialStep.EQUIP
            await session.commit()
            await send_dialogue(interaction, lines, title="🔧 Install Your Parts")

        elif step == TutorialStep.EQUIP and command_name == "equip":
            # Check if all 7 slots are filled
            from db.models import Build

            build_result = await session.execute(
                select(Build).where(
                    Build.user_id == user.discord_id,
                    Build.is_active,
                )
            )
            build = build_result.scalar_one_or_none()
            if build:
                slots = build.slots
                has_reactor = slots.get("reactor") is not None
                has_drive = slots.get("drive") is not None
                has_thrusters = slots.get("thrusters") is not None
                has_hull = slots.get("hull") is not None
                has_stabilizers = slots.get("stabilizers") is not None
                has_retros = slots.get("retros") is not None
                has_overdrive = slots.get("overdrive") is not None

                all_filled = (
                    has_reactor
                    and has_drive
                    and has_thrusters
                    and has_hull
                    and has_stabilizers
                    and has_retros
                    and has_overdrive
                )

                if all_filled:
                    user.tutorial_step = TutorialStep.MINT
                    await session.commit()
                    await send_dialogue(
                        interaction,
                        dialogue["teach_build_preview"],
                        title="🚀 All Slots Filled",
                    )
                else:
                    missing = []
                    if not has_reactor:
                        missing.append("Reactor")
                    if not has_drive:
                        missing.append("Drive")
                    if not has_thrusters:
                        missing.append("Thrusters")
                    if not has_hull:
                        missing.append("Hull")
                    if not has_stabilizers:
                        missing.append("Stabilizers")
                    if not has_retros:
                        missing.append("Retros")
                    if not has_overdrive:
                        missing.append("Overdrive")
                    await send_dialogue(
                        interaction,
                        [
                            f"Good, that's bolted on. Still need: **{', '.join(missing)}**. Keep going."  # noqa: E501
                        ],
                        title="🔧 Not Done Yet",
                    )

        elif step == TutorialStep.MINT and command_name == "build_preview":
            await send_dialogue(
                interaction,
                dialogue["teach_build_mint"],
                title="📄 Mint Your Ship Title",
            )

        elif step == TutorialStep.MINT and command_name == "build_mint":
            user.tutorial_step = TutorialStep.GARAGE
            await session.commit()
            await send_dialogue(
                interaction,
                dialogue["teach_garage"],
                title="🏗️ Check Your Build",
            )

        elif step == TutorialStep.GARAGE and command_name == "hangar":
            user.tutorial_step = TutorialStep.RACE
            await session.commit()
            await send_dialogue(
                interaction,
                dialogue["teach_race"],
                title="🏁 Time for Payback",
            )

        elif step == TutorialStep.RACE and command_name == "race":
            did_win = kwargs.get("did_win", False)
            uid = interaction.user.id

            view = await send_dialogue(
                interaction,
                dialogue["race_win"] if did_win else dialogue["race_lose"],
                title="🏁 Race Complete",
                with_continue=True,
                user_id=uid,
            )
            user.tutorial_step = TutorialStep.PACK
            await session.commit()
            await view.wait_for_click()

            from bot.cogs.cards import _PackRevealView
            from bot.reveal import PartRevealEntry

            starter_cards, pack_cards = await _grant_tutorial_completion(session, user)
            await session.commit()

            # Show the starter cards they're keeping as a scrollable widget
            if starter_cards:
                await send_dialogue(
                    interaction,
                    [
                        "Those salvage parts? They're yours for real now. Not much, but enough to race."  # noqa: E501
                    ],
                    title="🔧 Starter Parts",
                )
                # Starter cards are bare Card objects — synthesize a PartRevealEntry per card
                # with a sentinel serial_number=0 (these are not minted into UserCard rows).
                starter_entries = [
                    PartRevealEntry(
                        name=card.name,
                        rarity=card.rarity.value,
                        slot=card.slot.value,
                        serial_number=0,
                        print_max=card.print_max,
                        primary_stats=card.stats.get("primary", {}),
                        secondary_stats=card.stats.get("secondary", {}),
                    )
                    for card in starter_cards
                ]
                starter_view = _PackRevealView(
                    entries=starter_entries,
                    display_name="Starter Parts",
                    owner_id=interaction.user.id,
                )
                await interaction.followup.send(
                    embed=starter_view.build_embed(), view=starter_view, ephemeral=True
                )

            await send_dialogue(
                interaction,
                dialogue["teach_pack"],
                title="🎴 Salvage Crate",
            )

            # Show the pack cards in the scrollable reveal widget
            pack_entries = [
                PartRevealEntry(
                    name=card.name,
                    rarity=card.rarity.value,
                    slot=card.slot.value,
                    serial_number=uc.serial_number,
                    print_max=card.print_max,
                    primary_stats=card.stats.get("primary", {}),
                    secondary_stats=card.stats.get("secondary", {}),
                )
                for card, uc in pack_cards
            ]
            pack_view = _PackRevealView(
                entries=pack_entries, display_name="Salvage Crate", owner_id=interaction.user.id
            )
            await interaction.followup.send(
                embed=pack_view.build_embed(), view=pack_view, ephemeral=True
            )

            view = await send_dialogue(
                interaction,
                dialogue["teach_daily"],
                title="💰 Daily Rewards",
                with_continue=True,
                user_id=uid,
            )
            await view.wait_for_click()

            await send_dialogue(
                interaction,
                ["Here's **1,000 Creds** to get you started. Don't blow it all on one crate."]
                + dialogue["outro"],
                title="🏁 You're In. Good Luck.",
                color=0x22C55E,
            )


async def _grant_tutorial_completion(
    session: AsyncSession, user: User
) -> tuple[list[Card], list[tuple[Card, UserCard]]]:
    """
    Grant all rewards a player gets from completing the tutorial.

    Returns (starter_cards, pack_minted) where pack_minted is a list of
    (Card, UserCard) tuples. Callers wrap these in `PartRevealEntry`
    adapters before passing to `_PackRevealView`.
    Caller must commit the session afterward.
    """
    from bot.cogs.cards import _grant_card, _roll_cards
    from engine.card_mint import delete_tutorial_cards, mint_card

    data = _load_tutorial_data()

    # Clean up any tutorial dummy cards
    await delete_tutorial_cards(session, user.discord_id)

    # Mint real copies of the starter cards
    starter_names = data["starter_cards"]
    starter_cards: list[Card] = []
    for name in starter_names:
        card_result = await session.execute(select(Card).where(Card.name == name))
        card = card_result.scalar_one_or_none()
        if card:
            await mint_card(session, user.discord_id, card)
            starter_cards.append(card)

    # Roll and grant a full salvage crate
    from config.settings import settings

    pack_cards = await _roll_cards(session, "salvage_crate", settings.JUNKYARD_PACK_SIZE)
    pack_minted: list[tuple[Card, UserCard]] = []
    for card in pack_cards:
        uc = await _grant_card(session, user.discord_id, card)
        pack_minted.append((card, uc))

    # Mark complete and grant creds
    user.tutorial_step = TutorialStep.COMPLETE
    user.currency += 1000
    users_registered.inc()

    return starter_cards, pack_minted


class TutorialCog(commands.Cog):
    """Manages the new-player tutorial flow."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="skip_tutorial", description="Skip the tutorial and jump straight into racing"
    )  # noqa: E501
    @traced_command
    async def skip_tutorial(self, interaction: discord.Interaction) -> None:
        from bot.cogs.cards import RARITY_EMOJI

        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            if is_tutorial_complete(user):
                await interaction.response.send_message(
                    "You already finished the tutorial.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)

            starter_cards, pack_cards = await _grant_tutorial_completion(session, user)
            await session.commit()

        # Show what they got
        parts_lines = []
        for card in starter_cards:
            emoji = RARITY_EMOJI.get(card.rarity.value, "")
            parts_lines.append(f"{emoji} **{card.name}** [{card.slot.value.title()}]")

        pack_lines = []
        for card, _ in pack_cards:
            emoji = RARITY_EMOJI.get(card.rarity.value, "")
            pack_lines.append(f"{emoji} **{card.name}** [{card.slot.value.title()}]")

        embed = discord.Embed(
            title="⏩ Tutorial Skipped",
            description=(
                "No story for you. Here's the short version: your uncle died, you got robbed, "  # noqa: E501
                "you raided a salvage yard.\n\n"
                "**Starter Parts:**\n" + "\n".join(parts_lines) + "\n\n"
                "**Salvage Crate:**\n" + "\n".join(pack_lines) + "\n\n"
                "💰 **+1,000 Creds**\n\n"
                "Use `/autoequip best` to fill all 7 slots, then `/build mint` to mint your title. "
                "Most races are format-gated — Street is open, higher formats need the right build. "  # noqa: E501
                "Rare events also lock to a specific hull class. Good luck."
            ),
            color=0x22C55E,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TutorialCog(bot))
