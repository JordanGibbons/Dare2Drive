"""Persistent HangarView for the /hangar <build> command.

The View has one Select per crew slot. Selecting a crew option assigns that
crew to the slot; selecting the special 'Unassign' option clears the slot.
The View is registered globally at bot startup via `bot.add_view(HangarView())`
so button/select interactions survive restarts.

custom_id format:
    hangar:slot:<build_id>:<archetype_name>
    e.g. hangar:slot:12345678-1234-5678-1234-567812345678:PILOT

Select option values:
    A real crew_id UUID, OR the literal string "unassign".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import discord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Build,
    BuildActivity,
    CrewArchetype,
    CrewAssignment,
    CrewMember,
    User,
)
from engine.class_engine import slots_for_hull

CUSTOM_ID_PREFIX = "hangar:slot"
UNASSIGN_VALUE = "unassign"


def make_select_custom_id(build_id: uuid.UUID, archetype_name: str) -> str:
    return f"{CUSTOM_ID_PREFIX}:{build_id}:{archetype_name}"


def parse_select_custom_id(custom_id: str) -> tuple[uuid.UUID, str] | None:
    """Return (build_id, archetype_name) if `custom_id` matches the hangar slot format."""
    parts = custom_id.split(":")
    if len(parts) != 4 or parts[0] != "hangar" or parts[1] != "slot":
        return None
    try:
        build_uuid = uuid.UUID(parts[2])
    except ValueError:
        return None
    return build_uuid, parts[3]


class HangarView(discord.ui.View):
    """Persistent View that handles all /hangar crew-slot Select interactions."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    # interaction_check + _handle_assignment / _handle_unassignment land in Task 15.


async def render_hangar_view(
    session: AsyncSession,
    build: Build,
    user: User,
) -> tuple[discord.Embed, HangarView]:
    """Render the /hangar embed + interactive View for `build`."""
    is_locked = build.current_activity != BuildActivity.IDLE

    # Load current assignments
    rows = (
        await session.execute(
            select(CrewAssignment, CrewMember)
            .join(CrewMember, CrewAssignment.crew_id == CrewMember.id)
            .where(CrewAssignment.build_id == build.id)
        )
    ).all()
    aboard_by_archetype: dict[CrewArchetype, CrewMember] = {
        assignment.archetype: crew for assignment, crew in rows
    }

    # Build embed
    crew_lines: list[str] = []
    for slot in slots_for_hull(build.hull_class):
        crew = aboard_by_archetype.get(slot)
        if crew is None:
            crew_lines.append(f"**{slot.name}** — empty")
        else:
            display = f'{crew.first_name} "{crew.callsign}" {crew.last_name} (Lvl {crew.level})'
            status = _crew_status_label(crew)
            crew_lines.append(f"**{slot.name}** — {display} — {status}")

    embed = discord.Embed(
        title=f"🚢 {build.name} ({build.hull_class.value.title()})",
        description="\n".join(["**Crew**", *crew_lines]),
    )
    if is_locked:
        embed.add_field(
            name="Status", value=f"Locked — {build.current_activity.value}", inline=False
        )

    # Build view: one Select per slot
    view = HangarView()
    if not is_locked:
        eligible_by_archetype = await _load_eligible_crew_by_archetype(
            session, user.discord_id, build.id
        )
        for slot in slots_for_hull(build.hull_class):
            current_crew = aboard_by_archetype.get(slot)
            select_component = _build_slot_select(
                build.id, slot, current_crew, eligible_by_archetype.get(slot, [])
            )
            view.add_item(select_component)
    else:
        # Disabled placeholder selects so the View shape stays consistent
        for slot in slots_for_hull(build.hull_class):
            placeholder = discord.ui.Select(
                custom_id=make_select_custom_id(build.id, slot.name),
                placeholder=f"{slot.name}: ship locked",
                options=[
                    discord.SelectOption(label="(ship is busy)", value="locked", default=True)
                ],
                disabled=True,
                min_values=1,
                max_values=1,
            )
            view.add_item(placeholder)

    return embed, view


def _crew_status_label(crew: CrewMember) -> str:
    now = datetime.now(timezone.utc)
    if crew.injured_until is not None and crew.injured_until > now:
        return "injured"
    return crew.current_activity.value if crew.current_activity else "idle"


async def _load_eligible_crew_by_archetype(
    session: AsyncSession, user_id: str, this_build_id: uuid.UUID
) -> dict[CrewArchetype, list[CrewMember]]:
    """Return crew owned by `user_id` not assigned to a different build, grouped by archetype."""
    rows = (
        await session.execute(
            select(CrewMember, CrewAssignment.build_id)
            .outerjoin(CrewAssignment, CrewMember.id == CrewAssignment.crew_id)
            .where(CrewMember.user_id == user_id)
        )
    ).all()
    out: dict[CrewArchetype, list[CrewMember]] = {}
    for crew, assigned_build_id in rows:
        if assigned_build_id is not None and assigned_build_id != this_build_id:
            continue
        out.setdefault(crew.archetype, []).append(crew)
    return out


def _build_slot_select(
    build_id: uuid.UUID,
    archetype: CrewArchetype,
    current_crew: CrewMember | None,
    eligible: list[CrewMember],
) -> discord.ui.Select:
    options: list[discord.SelectOption] = []
    if not eligible:
        options.append(
            discord.SelectOption(
                label=f"(no eligible {archetype.name.lower()}s)",
                value="none",
                default=True,
            )
        )
        return discord.ui.Select(
            custom_id=make_select_custom_id(build_id, archetype.name),
            placeholder=archetype.name,
            options=options,
            disabled=True,
            min_values=1,
            max_values=1,
        )

    # Discord caps Select options at 25; with the Unassign option we leave room for 24 crew
    for crew in eligible[:24]:
        label = f'{crew.first_name} "{crew.callsign}" {crew.last_name} (Lvl {crew.level})'[:100]
        is_current = current_crew is not None and crew.id == current_crew.id
        status = _crew_status_label(crew)
        description = f"{archetype.name.title()} · {status}"[:100]
        options.append(
            discord.SelectOption(
                label=label,
                value=str(crew.id),
                description=description,
                default=is_current,
            )
        )
    if current_crew is not None:
        options.append(
            discord.SelectOption(
                label="Unassign",
                value=UNASSIGN_VALUE,
                description=f"Remove from {archetype.name.title()} slot",
            )
        )

    return discord.ui.Select(
        custom_id=make_select_custom_id(build_id, archetype.name),
        placeholder=archetype.name,
        options=options,
        min_values=1,
        max_values=1,
    )
