"""Race cog — /race, /leaderboard, /wrecks commands."""

from __future__ import annotations

import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.cogs.tutorial import _load_tutorial_data, build_npc_race_data, is_tutorial_complete
from config.logging import get_logger
from db.models import (
    Build,
    CarClass,
    Card,
    CardSlot,
    Race,
    RigTitle,
    TutorialStep,
    User,
    UserCard,
    WreckLog,
)
from db.session import async_session
from engine.race_engine import RaceResult, compute_race

log = get_logger(__name__)

POSITION_EMOJI = {1: "🥇", 2: "🥈", 3: "🥉"}

# How many races a part lasts before wearing out, by slot and rarity.
# Tires/brakes wear fastest, chassis is tankiest. Higher rarity = longer life.
SLOT_BASE_LIFESPAN: dict[str, int] = {
    "tires": 5,
    "brakes": 6,
    "turbo": 7,
    "suspension": 8,
    "transmission": 10,
    "engine": 12,
    "chassis": 16,
}

RARITY_LIFESPAN_MULT: dict[str, float] = {
    "common": 1.0,
    "uncommon": 1.4,
    "rare": 1.8,
    "epic": 2.5,
    "legendary": 3.5,
    "ghost": 5.0,
}


def get_part_lifespan(slot: str, rarity: str) -> int:
    """Get the lifespan (in races) for a part based on its slot and rarity."""
    base = SLOT_BASE_LIFESPAN.get(slot, 10)
    mult = RARITY_LIFESPAN_MULT.get(rarity, 1.0)
    return max(1, round(base * mult))


async def _check_class_gate(
    session: AsyncSession, build_dict: dict[str, Any], required_class: CarClass
) -> str | None:
    """
    Return an error string if the build doesn't meet the class requirement,
    or None if it passes. STREET is always open — no title required.
    """
    if required_class == CarClass.STREET:
        return None

    # Non-STREET races require a minted Car Title with the matching class
    build_result = await session.execute(
        select(Build).where(
            Build.user_id == build_dict["user_id"],
            Build.is_active,
        )
    )
    build = build_result.scalar_one_or_none()
    if not build or not build.core_locked or not build.rig_title_id:
        return (
            f"❌ **{required_class.value.upper()}** races require a minted Car Title. "
            f"Fill all 7 slots and use `/build mint` first."
        )

    title = await session.get(RigTitle, build.rig_title_id)
    if not title or title.car_class != required_class:
        actual = title.car_class.value.upper() if title else "none"
        required = required_class.value.upper()
        return f"❌ Your rig is class **{actual}** — this race requires **{required}**."

    return None


async def _resolve_build_for_race(session: AsyncSession, user: User) -> dict[str, Any] | str:
    """
    Load a user's active build and resolve all card data for the race engine.
    Build.slots now maps slot_name → user_card_id (UUID of the specific copy).
    Returns the build dict or an error string.
    """
    from engine.card_mint import apply_stat_modifiers

    result = await session.execute(
        select(Build).where(Build.user_id == user.discord_id, Build.is_active)
    )
    build = result.scalar_one_or_none()
    if not build:
        return "No active build found."

    cards: dict[str, dict[str, Any]] = {}
    for slot in CardSlot:
        uc_id_str = build.slots.get(slot.value)
        if not uc_id_str:
            continue

        uc = await session.get(UserCard, uuid.UUID(uc_id_str))
        if not uc:
            # Copy was deleted (wreck); clear the slot
            continue
        if uc.user_id != user.discord_id:
            continue

        card = await session.get(Card, uc.card_id)
        if not card:
            continue

        # Apply per-copy stat modifiers to the base card stats
        effective_stats = apply_stat_modifiers(card.stats, uc.stat_modifiers or {})

        cards[uc_id_str] = {
            "id": str(uc.id),
            "card_id": str(card.id),
            "name": card.name,
            "slot": card.slot.value,
            "rarity": card.rarity.value,
            "stats": effective_stats,
        }

    if not cards:
        return "Your build has no cards equipped. Use `/equip` to add parts before racing!"

    # Check minimum required slots: engine, transmission, tires, chassis
    required_slots = {"engine", "transmission", "tires", "chassis"}
    filled_slots = set()
    for card_data in cards.values():
        filled_slots.add(card_data["slot"])
    missing = required_slots - filled_slots
    if missing:
        missing_str = ", ".join(s.title() for s in sorted(missing))
        return f"You need at least **Engine, Transmission, Tires, and Chassis** to race. Missing: **{missing_str}**."  # noqa: E501

    return {
        "user_id": user.discord_id,
        "slots": build.slots,
        "cards": cards,
        "body_type": (build.body_type or user.body_type).value,
    }


async def _apply_wreck_results(
    session: AsyncSession, race_result: RaceResult, race_id: uuid.UUID
) -> None:
    """Apply wreck part losses to the database and create WreckLog entries."""
    for placement in race_result.placements:
        if not placement.wrecked_parts:
            continue

        lost_parts_data = []
        for wp in placement.wrecked_parts:
            # wp.card_id is actually the user_card_id (UUID string from build slots)
            uc_id_str = wp.card_id
            if uc_id_str:
                uc = await session.get(UserCard, uuid.UUID(uc_id_str))
                if uc:
                    # Clear the slot in the active build
                    build_result = await session.execute(
                        select(Build).where(
                            Build.user_id == placement.user_id,
                            Build.is_active,
                        )
                    )
                    build = build_result.scalar_one_or_none()
                    if build:
                        new_slots = dict(build.slots)
                        for slot_name, slot_uc_id in new_slots.items():
                            if slot_uc_id == uc_id_str:
                                new_slots[slot_name] = None
                        build.slots = new_slots

                    # Delete the specific card copy
                    await session.delete(uc)

            lost_parts_data.append(wp.to_dict())

        # Create WreckLog
        wreck_log = WreckLog(
            race_id=race_id,
            user_id=placement.user_id,
            lost_parts=lost_parts_data,
        )
        session.add(wreck_log)


async def _run_race_and_send(
    interaction: discord.Interaction,
    challenger: User,
    challenger_build: dict[str, Any],
    opp_build: dict[str, Any],
    is_tutorial_race: bool,
    opp_display_name: str | None,
    opp_user: User | None,
    wager: int = 0,
) -> None:
    """Execute a race, save results, and send the result embed. Used by both PvP and tutorial flows."""  # noqa: E501
    async with async_session() as session:
        # Re-attach users to this session
        challenger = await session.get(User, challenger.discord_id)

        race_result = compute_race([challenger_build, opp_build])

        if not is_tutorial_race:
            # Store race record
            race_record = Race(
                participants={
                    "players": [challenger.discord_id, opp_build["user_id"]],
                },
                environment=race_result.environment.to_dict(),
                results=race_result.to_dict(),
            )
            session.add(race_record)
            await session.flush()

            # Apply wreck results
            await _apply_wreck_results(session, race_result, race_record.id)

        # Award XP and placement creds
        # When a wager is active, skip cred bonuses — the wager IS the reward
        for placement in race_result.placements:
            if placement.user_id.startswith("NPC_"):
                continue
            user = await session.get(User, placement.user_id)
            if user:
                if placement.is_tie:
                    pass  # Tie — no XP, no creds
                elif placement.dnf:
                    user.xp += 5
                elif placement.position == 1:
                    user.xp += 50
                    if wager == 0:
                        user.currency += 100
                elif placement.position == 2:
                    user.xp += 25
                    if wager == 0:
                        user.currency += 50
                else:
                    user.xp += 10

        # Handle wager — winner takes all (1v1)
        if wager > 0 and not is_tutorial_race:
            winner_p = next(
                (p for p in race_result.placements if p.position == 1 and not p.is_tie), None
            )
            if winner_p:
                # Deduct from loser(s), give to winner
                for build_data in [challenger_build, opp_build]:
                    uid = build_data["user_id"]
                    if uid == winner_p.user_id:
                        continue
                    u = await session.get(User, uid)
                    if u:
                        u.currency -= wager
                winner_user = await session.get(User, winner_p.user_id)
                if winner_user:
                    winner_user.currency += wager

        # Degrade equipped parts and track wear for all real players
        from engine.card_mint import degrade_stat_modifiers

        worn_out_parts: list[tuple[str, str, str]] = []  # (user_id, slot_name, card_name)

        for build_data in [challenger_build, opp_build]:
            uid = build_data["user_id"]
            if uid.startswith("NPC_"):
                continue
            # Severity based on race conditions — harsher weather = more wear
            base_severity = 0.003
            env_name = race_result.environment.name if race_result.environment else ""
            if env_name in ("blizzard", "monsoon", "sandstorm"):
                severity = base_severity * 2
            elif env_name in ("rain", "fog", "heat_wave"):
                severity = base_severity * 1.5
            else:
                severity = base_severity
            # DNF = more damage from the crash
            placement = next((p for p in race_result.placements if p.user_id == uid), None)
            if placement and placement.dnf:
                severity *= 2

            for slot_name, uc_id_str in build_data["slots"].items():
                if not uc_id_str or uc_id_str.startswith("npc_"):
                    continue
                uc = await session.get(UserCard, uuid.UUID(uc_id_str))
                if not uc:
                    continue

                # Degrade stat modifiers
                if uc.stat_modifiers:
                    uc.stat_modifiers = degrade_stat_modifiers(uc.stat_modifiers, severity)

                # Increment wear counter
                uc.races_used += 1

                # Check if part has worn out
                card_data = build_data["cards"].get(uc_id_str, {})
                card_rarity = card_data.get("rarity", "common")
                lifespan = get_part_lifespan(slot_name, card_rarity)
                if uc.races_used >= lifespan:
                    card_name = card_data.get("name", slot_name.title())

                    # Clear from build
                    build_result = await session.execute(
                        select(Build).where(Build.user_id == uid, Build.is_active)
                    )
                    build = build_result.scalar_one_or_none()
                    if build:
                        new_slots = dict(build.slots)
                        new_slots[slot_name] = None
                        build.slots = new_slots

                    await session.delete(uc)
                    worn_out_parts.append((uid, slot_name, card_name))
                    log.info(
                        "Part worn out: user=%s slot=%s card=%s after %d races",
                        uid,
                        slot_name,
                        card_name,
                        lifespan,
                    )

        await session.commit()

    # Build display name map
    display_names: dict[str, str] = {
        challenger.discord_id: f"<@{challenger.discord_id}>",
    }
    if is_tutorial_race and opp_display_name:
        display_names[opp_build["user_id"]] = opp_display_name
    elif not is_tutorial_race and opp_user:
        display_names[opp_user.discord_id] = f"<@{opp_user.discord_id}>"

    # Build result embed
    env = race_result.environment
    embed = discord.Embed(
        title=f"🏁 Race — {env.display_name}",
        description=env.description,
        color=0xF59E0B,
    )

    for p in race_result.placements:
        pos_emoji = POSITION_EMOJI.get(p.position, f"P{p.position}")
        label = display_names.get(p.user_id, p.user_id)
        if p.is_tie:
            if p.dnf:
                status = f"🤝 TIE — DNF at {p.distance_pct * 100:.0f}%"
            else:
                status = f"🤝 TIE — {p.score:.1f} pts"
        elif p.dnf:
            if race_result.all_dnf:
                status = f"💥 DNF — {p.distance_pct * 100:.0f}% complete"
            else:
                status = "💥 DNF"
        else:
            status = f"{p.score:.1f} pts"
        embed.add_field(
            name=f"{pos_emoji} {status}",
            value=f"{label}\n{p.narrative}",
            inline=False,
        )

    if wager > 0 and not is_tutorial_race:
        winner_p = next(
            (p for p in race_result.placements if p.position == 1 and not p.is_tie), None
        )
        if winner_p:
            winner_label = display_names.get(winner_p.user_id, "?")
            embed.add_field(
                name="💰 Wager",
                value=f"{winner_label} wins **{wager} Creds**!",
                inline=False,
            )
        else:
            embed.add_field(name="💰 Wager", value="Tie — no creds exchanged.", inline=False)

    if race_result.wrecks:
        wreck_lines = []
        for w in race_result.wrecks:
            parts = ", ".join(wp["card_name"] for wp in w["lost_parts"])
            label = display_names.get(w["user_id"], w["user_id"])
            wreck_lines.append(f"{label} lost: {parts}")
        embed.add_field(name="💥 Wrecks", value="\n".join(wreck_lines), inline=False)

    if worn_out_parts:
        wear_lines = []
        for uid, slot_name, card_name in worn_out_parts:
            label = display_names.get(uid, uid)
            wear_lines.append(f"{label} — **{card_name}** ({slot_name}) wore out")
        embed.add_field(name="🔧 Worn Out", value="\n".join(wear_lines), inline=False)

    await interaction.followup.send(embed=embed)

    # Tutorial progression
    if is_tutorial_race:
        from bot.cogs.tutorial import advance_tutorial

        player_placement = next(
            (p for p in race_result.placements if p.user_id == challenger.discord_id),
            None,
        )
        did_win = player_placement is not None and player_placement.position == 1
        await advance_tutorial(
            interaction,
            challenger.discord_id,
            "race",
            did_win=did_win,
        )


class _RaceRequestView(discord.ui.View):
    """Accept / decline a race challenge with optional wager."""

    def __init__(
        self,
        challenger: User,
        challenger_build: dict[str, Any],
        opponent: User,
        opponent_member: discord.Member,
        interaction: discord.Interaction,
        wager: int = 0,
    ) -> None:
        super().__init__(timeout=120)
        self.challenger = challenger
        self.challenger_build = challenger_build
        self.opponent = opponent
        self.opponent_member = opponent_member
        self.original_interaction = interaction
        self.wager = wager
        self.resolved = False

    @discord.ui.button(label="Accept Race", style=discord.ButtonStyle.success, emoji="🏁")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent_member.id:
            await interaction.response.send_message("This challenge isn't for you.", ephemeral=True)
            return

        # Disable buttons
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.resolved = True

        # Resolve opponent's build and verify wager funds for both players
        async with async_session() as session:
            opp_user = await session.get(User, self.opponent.discord_id)
            if not opp_user:
                await interaction.followup.send("Something went wrong — opponent not found.")
                self.stop()
                return

            if self.wager > 0:
                # Re-check challenger balance (may have changed since challenge was issued)
                chall_user = await session.get(User, self.challenger.discord_id)
                if chall_user and chall_user.currency < self.wager:
                    await interaction.followup.send(
                        f"❌ Challenger no longer has enough Creds for the **{self.wager}** wager. Race cancelled."  # noqa: E501
                    )
                    self.stop()
                    return

                if opp_user.currency < self.wager:
                    await interaction.followup.send(
                        f"❌ {self.opponent_member.display_name} doesn't have enough Creds for the {self.wager} wager."  # noqa: E501
                    )
                    self.stop()
                    return

            opp_build = await _resolve_build_for_race(session, opp_user)
            if isinstance(opp_build, str):
                await interaction.followup.send(
                    f"{self.opponent_member.display_name} can't race: {opp_build}"
                )
                self.stop()
                return

        wager_msg = f" for **{self.wager} Creds**" if self.wager > 0 else ""
        await interaction.followup.send(f"Race accepted{wager_msg}! Engines revving... 🏎️💨")

        await _run_race_and_send(
            interaction=self.original_interaction,
            challenger=self.challenger,
            challenger_build=self.challenger_build,
            opp_build=opp_build,
            is_tutorial_race=False,
            opp_display_name=None,
            opp_user=self.opponent,
            wager=self.wager,
        )
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent_member.id:
            await interaction.response.send_message("This challenge isn't for you.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.resolved = True

        await interaction.followup.send(
            f"🚫 {self.opponent_member.display_name} declined the race. Maybe next time."
        )
        self.stop()

    async def on_timeout(self) -> None:
        if not self.resolved:
            for item in self.children:
                item.disabled = True


class _MultiRaceView(discord.ui.View):
    """Join button for multi-race events. Max 3 players, 2-minute timer."""

    def __init__(
        self,
        host: User,
        host_build: dict[str, Any],
        host_member: discord.Member,
        interaction: discord.Interaction,
        wager: int = 0,
    ) -> None:
        super().__init__(timeout=120)  # 2 minutes
        self.host = host
        self.host_build = host_build
        self.host_member = host_member
        self.original_interaction = interaction
        self.wager = wager
        self.entrants: list[tuple[User, dict[str, Any], discord.Member]] = [
            (host, host_build, host_member)
        ]
        self.entrant_ids: set[int] = {host_member.id}
        self.started = False

    @discord.ui.button(label="Join Race (0/3)", style=discord.ButtonStyle.success, emoji="🏁")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.started:
            await interaction.response.send_message("Race already started.", ephemeral=True)
            return

        if interaction.user.id in self.entrant_ids:
            await interaction.response.send_message("You're already in!", ephemeral=True)
            return

        if len(self.entrants) >= 3:
            await interaction.response.send_message("Race is full!", ephemeral=True)
            return

        # Resolve their build
        async with async_session() as session:
            user = await session.get(User, str(interaction.user.id))
            if not user:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            if not is_tutorial_complete(user):
                await interaction.response.send_message(
                    "Finish the tutorial first!", ephemeral=True
                )
                return

            if self.wager > 0 and user.currency < self.wager:
                await interaction.response.send_message(
                    f"You need at least **{self.wager} Creds** to join this race.", ephemeral=True
                )
                return

            build = await _resolve_build_for_race(session, user)
            if isinstance(build, str):
                await interaction.response.send_message(build, ephemeral=True)
                return

        self.entrants.append((user, build, interaction.user))
        self.entrant_ids.add(interaction.user.id)

        # Update button label
        button.label = f"Join Race ({len(self.entrants)}/3)"
        if len(self.entrants) >= 3:
            button.disabled = True

        names = ", ".join(m.display_name for _, _, m in self.entrants)
        (
            self.original_interaction.message.embeds[0]
            if hasattr(self.original_interaction, "message")
            else None
        )
        # Just edit the view to update the button
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"**{interaction.user.display_name}** joined! ({len(self.entrants)}/3)\nRacers: {names}",  # noqa: E501
        )

    async def on_timeout(self) -> None:
        if self.started:
            return
        self.started = True

        if len(self.entrants) < 2:
            await self.original_interaction.followup.send(
                "Not enough racers joined. Race cancelled."
            )
            return

        # Disable button
        for item in self.children:
            item.disabled = True

        await self.original_interaction.followup.send(
            f"⏱️ Timer's up! **{len(self.entrants)} racers** — starting the race! 🏎️💨"
        )

        # Run the multi-race
        all_builds = [build for _, build, _ in self.entrants]
        race_result = compute_race(all_builds)

        async with async_session() as session:
            # Store race record
            race_record = Race(
                participants={"players": [u.discord_id for u, _, _ in self.entrants]},
                environment=race_result.environment.to_dict(),
                results=race_result.to_dict(),
            )
            session.add(race_record)
            await session.flush()

            await _apply_wreck_results(session, race_result, race_record.id)

            # Award XP and placement creds
            # When a wager is active, skip cred bonuses — the wager IS the reward
            for placement in race_result.placements:
                if placement.user_id.startswith("NPC_"):
                    continue
                user = await session.get(User, placement.user_id)
                if user:
                    if placement.is_tie:
                        pass
                    elif placement.dnf:
                        user.xp += 5
                    elif placement.position == 1:
                        user.xp += 50
                        if self.wager == 0:
                            user.currency += 100
                    elif placement.position == 2:
                        user.xp += 25
                        if self.wager == 0:
                            user.currency += 50
                    else:
                        user.xp += 10

            # Handle wager — winner takes all
            if self.wager > 0:
                winner_placement = next(
                    (p for p in race_result.placements if p.position == 1 and not p.is_tie), None
                )
                if winner_placement:
                    # Deduct from losers, give to winner
                    for u, _, _ in self.entrants:
                        if u.discord_id == winner_placement.user_id:
                            continue
                        user = await session.get(User, u.discord_id)
                        if user:
                            user.currency -= self.wager
                    winner = await session.get(User, winner_placement.user_id)
                    if winner:
                        winner.currency += self.wager * (len(self.entrants) - 1)

            # Part degradation and wear tracking
            from engine.card_mint import degrade_stat_modifiers

            multi_worn_out: list[tuple[str, str, str]] = []

            for build_data in all_builds:
                uid = build_data["user_id"]
                if uid.startswith("NPC_"):
                    continue
                base_severity = 0.003
                env_name = race_result.environment.name if race_result.environment else ""
                if env_name in ("blizzard", "monsoon", "sandstorm"):
                    severity = base_severity * 2
                elif env_name in ("rain", "fog", "heat_wave"):
                    severity = base_severity * 1.5
                else:
                    severity = base_severity
                placement = next((p for p in race_result.placements if p.user_id == uid), None)
                if placement and placement.dnf:
                    severity *= 2
                for slot_name, uc_id_str in build_data["slots"].items():
                    if not uc_id_str or uc_id_str.startswith("npc_"):
                        continue
                    uc = await session.get(UserCard, uuid.UUID(uc_id_str))
                    if not uc:
                        continue
                    if uc.stat_modifiers:
                        uc.stat_modifiers = degrade_stat_modifiers(uc.stat_modifiers, severity)
                    uc.races_used += 1
                    card_data = build_data["cards"].get(uc_id_str, {})
                    card_rarity = card_data.get("rarity", "common")
                    lifespan = get_part_lifespan(slot_name, card_rarity)
                    if uc.races_used >= lifespan:
                        card_name = card_data.get("name", slot_name.title())
                        build_result = await session.execute(
                            select(Build).where(Build.user_id == uid, Build.is_active)
                        )
                        build = build_result.scalar_one_or_none()
                        if build:
                            new_slots = dict(build.slots)
                            new_slots[slot_name] = None
                            build.slots = new_slots
                        await session.delete(uc)
                        multi_worn_out.append((uid, slot_name, card_name))

            await session.commit()

        # Build display names
        display_names: dict[str, str] = {}
        for u, _, m in self.entrants:
            display_names[u.discord_id] = f"<@{u.discord_id}>"

        env = race_result.environment
        embed = discord.Embed(
            title=f"🏁 Multi-Race — {env.display_name}",
            description=env.description,
            color=0xF59E0B,
        )

        for p in race_result.placements:
            pos_emoji = POSITION_EMOJI.get(p.position, f"P{p.position}")
            label = display_names.get(p.user_id, p.user_id)
            if p.is_tie:
                status = (
                    f"🤝 TIE — {p.distance_pct * 100:.0f}%"
                    if p.dnf
                    else f"🤝 TIE — {p.score:.1f} pts"
                )
            elif p.dnf:
                status = (
                    f"💥 DNF — {p.distance_pct * 100:.0f}% complete"
                    if race_result.all_dnf
                    else "💥 DNF"
                )
            else:
                status = f"{p.score:.1f} pts"
            embed.add_field(
                name=f"{pos_emoji} {status}", value=f"{label}\n{p.narrative}", inline=False
            )

        if self.wager > 0:
            winner_p = next(
                (p for p in race_result.placements if p.position == 1 and not p.is_tie), None
            )
            if winner_p:
                total = self.wager * (len(self.entrants) - 1)
                embed.add_field(
                    name="💰 Wager",
                    value=f"{display_names.get(winner_p.user_id, '?')} wins **{total} Creds**!",
                    inline=False,
                )
            else:
                embed.add_field(name="💰 Wager", value="Tie — no creds exchanged.", inline=False)

        if race_result.wrecks:
            wreck_lines = []
            for w in race_result.wrecks:
                parts = ", ".join(wp["card_name"] for wp in w["lost_parts"])
                label = display_names.get(w["user_id"], w["user_id"])
                wreck_lines.append(f"{label} lost: {parts}")
            embed.add_field(name="💥 Wrecks", value="\n".join(wreck_lines), inline=False)

        if multi_worn_out:
            wear_lines = []
            for uid, slot_name, card_name in multi_worn_out:
                label = display_names.get(uid, uid)
                wear_lines.append(f"{label} — **{card_name}** ({slot_name}) wore out")
            embed.add_field(name="🔧 Worn Out", value="\n".join(wear_lines), inline=False)

        await self.original_interaction.followup.send(embed=embed)


class RaceCog(commands.Cog):
    """Racing, challenges, and leaderboards."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="race", description="Challenge another player to a race")
    @app_commands.describe(
        opponent="The player to race against",
        wager="Creds to bet (min 10, winner takes all)",
        race_class="Race class (default: Street — open to all builds)",
    )
    @app_commands.choices(
        race_class=[
            app_commands.Choice(name="🛣️ Street (open)", value="street"),
            app_commands.Choice(name="💨 Drag", value="drag"),
            app_commands.Choice(name="🏁 Circuit", value="circuit"),
            app_commands.Choice(name="🌀 Drift", value="drift"),
            app_commands.Choice(name="⛰️ Rally", value="rally"),
            app_commands.Choice(name="👑 Elite", value="elite"),
        ]
    )
    async def race(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member | None = None,
        wager: int = 0,
        race_class: str = "street",
    ) -> None:
        if wager != 0 and wager < 10:
            await interaction.response.send_message(
                "Minimum wager is **10 Creds**.", ephemeral=True
            )
            return
        if wager < 0:
            await interaction.response.send_message("Wager can't be negative.", ephemeral=True)
            return
        async with async_session() as session:
            challenger = await session.get(User, str(interaction.user.id))
            if not challenger:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            is_tutorial_race = challenger.tutorial_step == TutorialStep.RACE

            challenger_build = await _resolve_build_for_race(session, challenger)
            if isinstance(challenger_build, str):
                await interaction.response.send_message(challenger_build, ephemeral=True)
                return

            # --- Class gate (skip for tutorial races) ---
            required_class = CarClass(race_class)
            if not is_tutorial_race and required_class != CarClass.STREET:
                gate_error = await _check_class_gate(session, challenger_build, required_class)
                if gate_error:
                    await interaction.response.send_message(gate_error, ephemeral=True)
                    return

            # --- Tutorial NPC race (instant, no request needed) ---
            if is_tutorial_race:
                await interaction.response.defer()
                npc_data = _load_tutorial_data()["npc_opponent"]
                opp_build = build_npc_race_data()
                await _run_race_and_send(
                    interaction=interaction,
                    challenger=challenger,
                    challenger_build=challenger_build,
                    opp_build=opp_build,
                    is_tutorial_race=True,
                    opp_display_name=npc_data["name"],
                    opp_user=None,
                )
                return

            # --- PvP race request ---
            if not opponent:
                await interaction.response.send_message(
                    "You need to challenge someone! Use `/race @player`.", ephemeral=True
                )
                return

            if opponent.id == interaction.user.id:
                await interaction.response.send_message(
                    "You can't race yourself. That's just running.", ephemeral=True
                )
                return

            if opponent.bot:
                await interaction.response.send_message("Bots don't race.", ephemeral=True)
                return

            opp_user = await session.get(User, str(opponent.id))
            if not opp_user:
                await interaction.response.send_message(
                    f"{opponent.display_name} hasn't started playing yet!", ephemeral=True
                )
                return

            if not is_tutorial_complete(opp_user):
                await interaction.response.send_message(
                    f"{opponent.display_name} is still in the tutorial.", ephemeral=True
                )
                return

            if wager > 0 and challenger.currency < wager:
                await interaction.response.send_message(
                    f"You don't have enough Creds for that wager! Have {challenger.currency}, need {wager}.",  # noqa: E501
                    ephemeral=True,
                )
                return

        # Send the race request
        view = _RaceRequestView(
            challenger=challenger,
            challenger_build=challenger_build,
            opponent=opp_user,
            opponent_member=opponent,
            interaction=interaction,
            wager=wager,
        )
        wager_text = f"\n💰 **Wager: {wager} Creds** — winner takes all!" if wager > 0 else ""
        embed = discord.Embed(
            title="🏁 Race Challenge",
            description=(
                f"{interaction.user.mention} is revving their engine and calling you out!\n"
                f"{wager_text}\n"
                f"{opponent.mention}, you in?"
            ),
            color=0xF59E0B,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="multirace", description="Host a multi-player race event (2-min signup, max 3)"
    )
    @app_commands.describe(wager="Optional creds wager (min 10, winner takes all)")
    async def multirace(self, interaction: discord.Interaction, wager: int = 0) -> None:
        if wager != 0 and wager < 10:
            await interaction.response.send_message(
                "Minimum wager is **10 Creds**.", ephemeral=True
            )
            return
        if wager < 0:
            await interaction.response.send_message("Wager can't be negative.", ephemeral=True)
            return

        async with async_session() as session:
            host = await session.get(User, str(interaction.user.id))
            if not host:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            if not is_tutorial_complete(host):
                await interaction.response.send_message(
                    "Finish the tutorial first!", ephemeral=True
                )
                return

            host_build = await _resolve_build_for_race(session, host)
            if isinstance(host_build, str):
                await interaction.response.send_message(host_build, ephemeral=True)
                return

            if wager > 0 and host.currency < wager:
                await interaction.response.send_message(
                    f"You need at least **{wager} Creds** to host with that wager.", ephemeral=True
                )
                return

        # Roll environment preview
        from engine.environment import roll_environment

        env = roll_environment()

        view = _MultiRaceView(
            host=host,
            host_build=host_build,
            host_member=interaction.user,
            interaction=interaction,
            wager=wager,
        )
        wager_text = f"\n💰 **Wager: {wager} Creds** — winner takes all!" if wager > 0 else ""
        embed = discord.Embed(
            title="🏁 Multi-Race Event!",
            description=(
                f"{interaction.user.mention} is hosting a race!\n"
                f"**Track:** {env.display_name}\n"
                f"**Conditions:** {env.description}\n"
                f"{wager_text}\n\n"
                f"⏱️ **2 minutes** to join (max 3 racers)\n"
                f"Minimum parts: Engine, Transmission, Tires, Chassis"
            ),
            color=0xF59E0B,
        )
        embed.set_footer(text=f"Hosted by {interaction.user.display_name} • 1/3 racers")
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="leaderboard", description="View the top racers")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            result = await session.execute(select(User).order_by(User.xp.desc()).limit(10))
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
            await interaction.response.send_message(
                "No wreck history — keep it clean! 🏁", ephemeral=True
            )
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
