"""Race cog — /race, /leaderboard, /wrecks commands."""

from __future__ import annotations

import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.metrics import parts_destroyed, races_completed, races_started
from bot.cogs.tutorial import _load_tutorial_data, build_npc_race_data, is_tutorial_complete
from bot.system_gating import get_active_system, system_required_message
from config.logging import get_logger
from config.metrics import trace_exemplar
from config.tracing import traced_command
from db.models import (
    Build,
    Card,
    CardSlot,
    CrewAssignment,
    CrewMember,
    HullClass,
    Race,
    RaceFormat,
    ShipTitle,
    TutorialStep,
    User,
    UserCard,
    WreckLog,
)
from db.session import async_session
from engine.crew_xp import award_xp
from engine.race_engine import RaceResult, compute_race

log = get_logger(__name__)

POSITION_EMOJI = {1: "🥇", 2: "🥈", 3: "🥉"}

# How many races a part lasts before wearing out, by slot and rarity.
# Thrusters/retros wear fastest, hull is tankiest. Higher rarity = longer life.
SLOT_BASE_LIFESPAN: dict[str, int] = {
    "thrusters": 5,
    "retros": 6,
    "overdrive": 7,
    "stabilizers": 8,
    "drive": 10,
    "reactor": 12,
    "hull": 16,
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


def _subclass_str(race_format: RaceFormat, hull_class: HullClass | None) -> str:
    """Format a subclass label for error messages, e.g. 'Sprint Hauler'."""
    hull = hull_class.value.title() if hull_class else ""
    return f"{race_format.value.title()} {hull}".strip()


async def _check_class_gate(
    session: AsyncSession,
    build_dict: dict[str, Any],
    required_format: RaceFormat,
    required_hull: HullClass | None = None,
) -> str | None:
    """
    Return an error string if the build doesn't meet the race requirements, or None if it passes.

    SPRINT with no hull class requirement is always open (no title needed).
    Any other format or a hull class requirement needs a minted Ship Title.
    """
    sprint_open = required_format == RaceFormat.SPRINT and required_hull is None
    if sprint_open:
        return None

    build = await session.get(Build, uuid.UUID(build_dict["build_id"]))
    if not build or not build.core_locked or not build.ship_title_id:
        req_str = _subclass_str(required_format, required_hull)
        return (
            f"❌ **{req_str}** races require a minted Ship Title. "
            "Fill all 7 slots and use `/build mint` first."
        )

    title = await session.get(ShipTitle, build.ship_title_id)
    if not title:
        return "❌ Ship Title not found. Try `/build mint` again."

    errors = []
    if title.race_format != required_format:
        errors.append(
            f"format **{title.race_format.value.title()}** "
            f"(need **{required_format.value.title()}**)"
        )
    if required_hull and title.hull_class != required_hull:
        errors.append(
            f"hull **{title.hull_class.value.title()}** "
            f"(need **{required_hull.value.title()}**)"
        )

    if errors:
        req_str = _subclass_str(required_format, required_hull)
        return f"❌ Your ship doesn't qualify for **{req_str}** — wrong {' and '.join(errors)}."

    return None


async def _resolve_build_for_race(
    session: AsyncSession, user: User, build_id: str | None = None
) -> dict[str, Any] | str:
    """
    Load a build for the race engine, resolving all card data.
    Build.slots maps slot_name → user_card_id (UUID of the specific copy).
    If build_id is given, loads that specific build; otherwise loads the default (is_active).
    Returns the build dict or an error string.
    """
    from engine.card_mint import apply_stat_modifiers

    if build_id:
        try:
            bid = uuid.UUID(build_id)
        except ValueError:
            return "Invalid build selection."
        result = await session.execute(
            select(Build).where(Build.id == bid, Build.user_id == user.discord_id)
        )
    else:
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

    # Check minimum required slots: reactor, drive, thrusters, hull
    required_slots = {"reactor", "drive", "thrusters", "hull"}
    filled_slots = set()
    for card_data in cards.values():
        filled_slots.add(card_data["slot"])
    missing = required_slots - filled_slots
    if missing:
        missing_str = ", ".join(s.title() for s in sorted(missing))
        return f"You need at least **Reactor, Drive, Thrusters, and Hull** to race. Missing: **{missing_str}**."  # noqa: E501

    return {
        "user_id": user.discord_id,
        "slots": build.slots,
        "cards": cards,
        "hull_class": (
            (build.hull_class or user.hull_class).value
            if (build.hull_class or user.hull_class)
            else None
        ),
        "build_id": str(build.id),
    }


async def _load_assigned_crew_for_user(
    session: AsyncSession, user_id: str
) -> tuple[uuid.UUID | None, list[CrewMember]]:
    """Return (active_build_id, list_of_assigned_crew) for a user, or (None, [])."""
    if user_id.startswith("NPC_"):
        return None, []
    result = await session.execute(
        select(Build).where(Build.user_id == user_id, Build.is_active.is_(True)).limit(1)
    )
    build = result.scalar_one_or_none()
    if build is None:
        return None, []

    ca_result = await session.execute(
        select(CrewMember)
        .join(CrewAssignment, CrewAssignment.crew_id == CrewMember.id)
        .where(CrewAssignment.build_id == build.id)
    )
    return build.id, list(ca_result.scalars().all())


async def _award_xp_to_crew(
    session: AsyncSession,
    builds_with_crew: list[dict[str, Any]],
    race_result: RaceResult,
) -> dict[str, list[tuple[CrewMember, int]]]:
    """For each placement, award XP to that user's crew. Returns user_id → list of
    (member, new_level) for crew that leveled up (used for embed footer)."""
    level_ups: dict[str, list[tuple[CrewMember, int]]] = {}
    pos_by_user = {p.user_id: p.position for p in race_result.placements}
    for build in builds_with_crew:
        user_id = build["user_id"]
        if user_id.startswith("NPC_"):
            continue
        crew = build.get("crew") or []
        position = pos_by_user.get(user_id)
        if position is None:
            continue
        xp_gain = 20 + (10 if position == 1 else 0)
        for member in crew:
            leveled = award_xp(member, xp_gain)
            if leveled:
                level_ups.setdefault(user_id, []).append((member, member.level))
    await session.flush()
    return level_ups


async def _apply_wreck_results(
    session: AsyncSession,
    race_result: RaceResult,
    race_id: uuid.UUID,
    build_id_map: dict[str, str] | None = None,
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
                    # Clear the slot in the raced build
                    bid_str = build_id_map.get(placement.user_id) if build_id_map else None
                    if bid_str:
                        build = await session.get(Build, uuid.UUID(bid_str))
                    else:
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
                    parts_destroyed.labels(reason="wreck").inc(exemplar=trace_exemplar())

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
    system_id: str | None = None,
) -> None:
    """Execute a race, save results, and send the result embed. Used by both PvP and tutorial flows."""  # noqa: E501
    race_type = "tutorial" if is_tutorial_race else "open"
    races_started.labels(race_type=race_type).inc(exemplar=trace_exemplar())

    async with async_session() as session:
        # Re-attach users to this session
        challenger = await session.get(User, challenger.discord_id)

        # Load assigned crew onto each real-player build before the race runs
        _, challenger_crew = await _load_assigned_crew_for_user(
            session, challenger_build["user_id"]
        )
        challenger_build["crew"] = challenger_crew
        _, opp_crew = await _load_assigned_crew_for_user(session, opp_build["user_id"])
        opp_build["crew"] = opp_crew

        race_result = compute_race([challenger_build, opp_build])

        # Award XP to crew based on placement (NPCs are skipped inside the helper)
        crew_level_ups = await _award_xp_to_crew(
            session, [challenger_build, opp_build], race_result
        )

        build_id_map = {
            bd["user_id"]: bd["build_id"]
            for bd in [challenger_build, opp_build]
            if "build_id" in bd
        }

        if not is_tutorial_race:
            # Store race record
            race_record = Race(
                participants={
                    "players": [challenger.discord_id, opp_build["user_id"]],
                },
                environment=race_result.environment.to_dict(),
                results=race_result.to_dict(),
                format=RaceFormat.SPRINT,
                system_id=system_id,
            )
            session.add(race_record)
            await session.flush()

            # Apply wreck results
            await _apply_wreck_results(session, race_result, race_record.id, build_id_map)

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

                    # Clear from raced build
                    bid_str = build_id_map.get(uid)
                    build = await session.get(Build, uuid.UUID(bid_str)) if bid_str else None
                    if build:
                        new_slots = dict(build.slots)
                        new_slots[slot_name] = None
                        build.slots = new_slots

                    await session.delete(uc)
                    worn_out_parts.append((uid, slot_name, card_name))
                    parts_destroyed.labels(reason="wear").inc(exemplar=trace_exemplar())
                    log.info(
                        "Part worn out: user=%s slot=%s card=%s after %d races",
                        uid,
                        slot_name,
                        card_name,
                        lifespan,
                    )

        # Update race_record on minted ships
        if not is_tutorial_race:
            for bd in [challenger_build, opp_build]:
                uid = bd["user_id"]
                if uid.startswith("NPC_"):
                    continue
                bid_str = build_id_map.get(uid)
                if not bid_str:
                    continue
                b = await session.get(Build, uuid.UUID(bid_str))
                if not b or not b.ship_title_id:
                    continue
                ship_title = await session.get(ShipTitle, b.ship_title_id)
                if not ship_title:
                    continue
                placement = next((p for p in race_result.placements if p.user_id == uid), None)
                if not placement or placement.is_tie:
                    continue
                rec = dict(ship_title.race_record or {"wins": 0, "losses": 0})
                if placement.position == 1:
                    rec["wins"] = rec.get("wins", 0) + 1
                else:
                    rec["losses"] = rec.get("losses", 0) + 1
                ship_title.race_record = rec

        await session.commit()

    # Record race completion metrics for each real player
    for placement in race_result.placements:
        if placement.user_id.startswith("NPC_"):
            continue
        if placement.dnf:
            # dnf = Did Not Finish; distinguish wrecks (part destroyed) from other DNFs
            outcome = "wreck" if placement.wrecked_parts else "dnf"
        elif placement.position == 1:
            outcome = "win"
        else:
            outcome = "loss"
        races_completed.labels(race_type=race_type, outcome=outcome).inc(exemplar=trace_exemplar())

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

    if crew_level_ups:
        level_lines = []
        for _user_id, bumps in crew_level_ups.items():
            for member, new_level in bumps:
                level_lines.append(
                    f'⭐ {member.first_name} "{member.callsign}" {member.last_name} '
                    f"reached Level {new_level}."
                )
        if level_lines:
            embed.add_field(
                name="Crew Level-Ups",
                value="\n".join(level_lines),
                inline=False,
            )

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
        system_id: str | None = None,
    ) -> None:
        super().__init__(timeout=120)
        self.challenger = challenger
        self.challenger_build = challenger_build
        self.opponent = opponent
        self.opponent_member = opponent_member
        self.original_interaction = interaction
        self.wager = wager
        self.system_id = system_id
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
        await interaction.followup.send(f"Race accepted{wager_msg}! Thrusters firing... 🚀💨")

        await _run_race_and_send(
            interaction=self.original_interaction,
            challenger=self.challenger,
            challenger_build=self.challenger_build,
            opp_build=opp_build,
            is_tutorial_race=False,
            opp_display_name=None,
            opp_user=self.opponent,
            wager=self.wager,
            system_id=self.system_id,
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
        system_id: str | None = None,
    ) -> None:
        super().__init__(timeout=120)  # 2 minutes
        self.host = host
        self.host_build = host_build
        self.host_member = host_member
        self.original_interaction = interaction
        self.wager = wager
        self.system_id = system_id
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
            f"⏱️ Timer's up! **{len(self.entrants)} racers** — launching! 🚀💨"
        )

        # Run the multi-race
        all_builds = [build for _, build, _ in self.entrants]

        async with async_session() as session:
            # Load assigned crew onto each real-player build before the race runs
            for build in all_builds:
                _, crew = await _load_assigned_crew_for_user(session, build["user_id"])
                build["crew"] = crew

            race_result = compute_race(all_builds)

            crew_level_ups = await _award_xp_to_crew(session, all_builds, race_result)

            build_id_map = {bd["user_id"]: bd["build_id"] for bd in all_builds if "build_id" in bd}

            # Store race record
            race_record = Race(
                participants={"players": [u.discord_id for u, _, _ in self.entrants]},
                environment=race_result.environment.to_dict(),
                results=race_result.to_dict(),
                format=RaceFormat.SPRINT,
                system_id=self.system_id,
            )
            session.add(race_record)
            await session.flush()

            await _apply_wreck_results(session, race_result, race_record.id, build_id_map)

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
                        bid_str = build_id_map.get(uid)
                        build = await session.get(Build, uuid.UUID(bid_str)) if bid_str else None
                        if build:
                            new_slots = dict(build.slots)
                            new_slots[slot_name] = None
                            build.slots = new_slots
                        await session.delete(uc)
                        multi_worn_out.append((uid, slot_name, card_name))

            # Update race_record on minted ships
            for bd in all_builds:
                uid = bd["user_id"]
                if uid.startswith("NPC_"):
                    continue
                bid_str = build_id_map.get(uid)
                if not bid_str:
                    continue
                b = await session.get(Build, uuid.UUID(bid_str))
                if not b or not b.ship_title_id:
                    continue
                ship_title = await session.get(ShipTitle, b.ship_title_id)
                if not ship_title:
                    continue
                placement = next((p for p in race_result.placements if p.user_id == uid), None)
                if not placement or placement.is_tie:
                    continue
                rec = dict(ship_title.race_record or {"wins": 0, "losses": 0})
                if placement.position == 1:
                    rec["wins"] = rec.get("wins", 0) + 1
                else:
                    rec["losses"] = rec.get("losses", 0) + 1
                ship_title.race_record = rec

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

        if crew_level_ups:
            level_lines = []
            for _user_id, bumps in crew_level_ups.items():
                for member, new_level in bumps:
                    level_lines.append(
                        f'⭐ {member.first_name} "{member.callsign}" {member.last_name} '
                        f"reached Level {new_level}."
                    )
            if level_lines:
                embed.add_field(
                    name="Crew Level-Ups",
                    value="\n".join(level_lines),
                    inline=False,
                )

        await self.original_interaction.followup.send(embed=embed)


async def _race_build_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for /race build param — shows only eligible builds."""
    race_format_val = getattr(interaction.namespace, "race_format", None) or "sprint"
    race_hull_val = getattr(interaction.namespace, "race_hull", None)

    required_format = RaceFormat(race_format_val)
    required_hull = HullClass(race_hull_val) if race_hull_val else None
    sprint_open = required_format == RaceFormat.SPRINT and required_hull is None

    async with async_session() as session:
        result = await session.execute(
            select(Build)
            .where(Build.user_id == str(interaction.user.id))
            .order_by(Build.is_active.desc())
        )
        builds = list(result.scalars().all())

        min_slots = {"reactor", "drive", "thrusters", "hull"}
        choices = []

        for b in builds:
            filled = {k for k, v in b.slots.items() if v is not None}
            if not min_slots.issubset(filled):
                continue

            if not sprint_open:
                if not b.ship_title_id or not b.core_locked:
                    continue
                title = await session.get(ShipTitle, b.ship_title_id)
                if not title or title.race_format != required_format:
                    continue
                if required_hull and title.hull_class != required_hull:
                    continue
                name = title.custom_name or title.auto_name or "Unnamed"
                fmt_str = title.race_format.value.title()
                hull_str = title.hull_class.value.title() if title.hull_class else ""
                label = f"{name} — {fmt_str} {hull_str}".strip()
            else:
                title = await session.get(ShipTitle, b.ship_title_id) if b.ship_title_id else None
                if title:
                    name = title.custom_name or title.auto_name or "Unnamed"
                    label = f"{name} — {title.race_format.value.title()}"
                else:
                    hc_str = b.hull_class.value.title() if b.hull_class else "Unknown"
                    label = f"{b.name or 'Build'} · {hc_str} ({len(filled)}/7)"

            if b.is_active:
                label += " ★"

            if current and current.lower() not in label.lower():
                continue

            choices.append(app_commands.Choice(name=label[:100], value=str(b.id)))

    return choices[:25]


class RaceCog(commands.Cog):
    """Racing, challenges, and leaderboards."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="race", description="Challenge another player to a race")
    @app_commands.describe(
        opponent="The ship to race against",
        wager="Creds to bet (min 10, winner takes all)",
        race_format="Race format (default: Sprint — open to all builds)",
        race_hull="Hull class filter (optional — combine with format for subclass events)",
        build="Which of your eligible ships to race with (default: your default build)",
    )
    @app_commands.choices(
        race_format=[
            app_commands.Choice(name="🛣️ Sprint (open)", value="sprint"),
            app_commands.Choice(name="💨 Endurance", value="endurance"),
            app_commands.Choice(name="🏁 Gauntlet", value="gauntlet"),
        ],
        race_hull=[
            app_commands.Choice(name="🚛 Hauler", value="hauler"),
            app_commands.Choice(name="⚔️ Skirmisher", value="skirmisher"),
            app_commands.Choice(name="🔭 Scout", value="scout"),
        ],
    )
    @app_commands.autocomplete(build=_race_build_autocomplete)
    @traced_command
    async def race(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member | None = None,
        wager: int = 0,
        race_format: str = "sprint",
        race_hull: str | None = None,
        build: str | None = None,
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
            system = await get_active_system(interaction, session)
            if system is None:
                await interaction.response.send_message(system_required_message(), ephemeral=True)
                return

        async with async_session() as session:
            challenger = await session.get(User, str(interaction.user.id))
            if not challenger:
                await interaction.response.send_message("Use `/start` first!", ephemeral=True)
                return

            is_tutorial_race = challenger.tutorial_step == TutorialStep.RACE

            challenger_build = await _resolve_build_for_race(session, challenger, build_id=build)
            if isinstance(challenger_build, str):
                await interaction.response.send_message(challenger_build, ephemeral=True)
                return

            # --- Format gate (skip for tutorial races) ---
            required_format = RaceFormat(race_format)
            required_hull = HullClass(race_hull) if race_hull else None
            has_requirements = required_format != RaceFormat.SPRINT or required_hull is not None
            if not is_tutorial_race and has_requirements:
                gate_error = await _check_class_gate(
                    session, challenger_build, required_format, required_hull
                )
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
                    system_id=system.channel_id,
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
                    "You can't race yourself. That's just drifting in circles.", ephemeral=True
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
            system_id=system.channel_id,
        )
        wager_text = f"\n💰 **Wager: {wager} Creds** — winner takes all!" if wager > 0 else ""
        embed = discord.Embed(
            title="🏁 Race Challenge",
            description=(
                f"{interaction.user.mention} is powering up their thrusters and calling you out!\n"
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
    @traced_command
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
            system = await get_active_system(interaction, session)
            if system is None:
                await interaction.response.send_message(system_required_message(), ephemeral=True)
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
            system_id=system.channel_id,
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
                f"Minimum parts: Reactor, Drive, Thrusters, Hull"
            ),
            color=0xF59E0B,
        )
        embed.set_footer(text=f"Hosted by {interaction.user.display_name} • 1/3 racers")
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="leaderboard", description="View the top racers")
    @traced_command
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            system = await get_active_system(interaction, session)
            if system is None:
                await interaction.response.send_message(system_required_message(), ephemeral=True)
                return

            result = await session.execute(select(User).order_by(User.xp.desc()).limit(10))
            users = list(result.scalars().all())

        if not users:
            await interaction.response.send_message("No pilots yet!")
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
    @traced_command
    async def wrecks(self, interaction: discord.Interaction) -> None:
        async with async_session() as session:
            system = await get_active_system(interaction, session)
            if system is None:
                await interaction.response.send_message(system_required_message(), ephemeral=True)
                return

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
