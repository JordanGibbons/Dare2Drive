"""HangarView + HangarSlotSelect for the /hangar <build> command.

Each crew slot is a `HangarSlotSelect` — a `discord.ui.DynamicItem` whose
custom_id encodes the build_id and archetype. The bot registers the
DynamicItem class once at startup; discord.py routes any incoming interaction
whose custom_id matches the template to `HangarSlotSelect.callback`,
surviving restarts.

The `HangarView` class is just a transient container — `render_hangar_view`
builds a fresh one per render and attaches the dynamic-item selects.

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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Build,
    BuildActivity,
    CrewArchetype,
    CrewAssignment,
    CrewMember,
    User,
)
from db.session import async_session
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
    """Transient container for HangarSlotSelect dynamic items."""

    def __init__(self) -> None:
        super().__init__(timeout=None)


class HangarSlotSelect(
    discord.ui.DynamicItem[discord.ui.Select],
    template=(r"hangar:slot:" r"(?P<build_id>[0-9a-fA-F-]{36}):" r"(?P<archetype>[A-Z]+)"),
):
    """A crew-slot Select whose custom_id encodes (build_id, archetype).

    Click routing is handled by discord.py's DynamicItem dispatch — `callback`
    runs on every interaction whose custom_id matches the template, surviving
    bot restarts.
    """

    def __init__(
        self,
        build_id: uuid.UUID,
        archetype: CrewArchetype,
        *,
        options: list[discord.SelectOption],
        placeholder: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            discord.ui.Select(
                custom_id=make_select_custom_id(build_id, archetype.name),
                options=options,
                placeholder=placeholder or archetype.name,
                disabled=disabled,
                min_values=1,
                max_values=1,
            )
        )
        self.build_id = build_id
        self.archetype = archetype

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):  # type: ignore[override]
        # The framework only uses this instance for callback dispatch — actual
        # selection values come from interaction.data, not the wrapped item.
        return cls(
            build_id=uuid.UUID(match["build_id"]),
            archetype=CrewArchetype[match["archetype"]],
            options=[discord.SelectOption(label="(stub)", value="stub")],
        )

    async def callback(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        values = (interaction.data or {}).get("values", [])
        if not values:
            return
        chosen = values[0]

        async with async_session() as session, session.begin():
            build = await session.get(Build, self.build_id, with_for_update=True)
            if build is None or build.user_id != str(interaction.user.id):
                await interaction.response.send_message("Build not found.", ephemeral=True)
                return
            if build.current_activity != BuildActivity.IDLE:
                await interaction.response.send_message(
                    f"`{build.name}` is currently busy and can't be modified.",
                    ephemeral=True,
                )
                return

            if chosen == UNASSIGN_VALUE:
                await session.execute(
                    delete(CrewAssignment)
                    .where(CrewAssignment.build_id == build.id)
                    .where(CrewAssignment.archetype == self.archetype)
                )
                msg = f"Unassigned the {self.archetype.name.title()} slot of `{build.name}`."
            elif chosen in {"none", "locked"}:
                return
            else:
                try:
                    crew_uuid = uuid.UUID(chosen)
                except ValueError:
                    await interaction.response.send_message("Invalid selection.", ephemeral=True)
                    return
                crew = await session.get(CrewMember, crew_uuid)
                if crew is None or crew.user_id != str(interaction.user.id):
                    await interaction.response.send_message(
                        "Crew member not found.", ephemeral=True
                    )
                    return
                if crew.archetype != self.archetype:
                    await interaction.response.send_message(
                        f"That crew member is a {crew.archetype.name.title()}, "
                        f"not a {self.archetype.name.title()}.",
                        ephemeral=True,
                    )
                    return
                # Upsert: replace any existing assignment for this slot.
                await session.execute(
                    delete(CrewAssignment)
                    .where(CrewAssignment.build_id == build.id)
                    .where(CrewAssignment.archetype == self.archetype)
                )
                session.add(
                    CrewAssignment(build_id=build.id, crew_id=crew.id, archetype=self.archetype)
                )
                msg = (
                    f'Assigned {crew.first_name} "{crew.callsign}" {crew.last_name} '
                    f"as {self.archetype.name.title()} of `{build.name}`."
                )

        await interaction.response.send_message(msg, ephemeral=True)


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

    # Build view: one HangarSlotSelect per slot
    view = HangarView()
    if not is_locked:
        eligible_by_archetype = await _load_eligible_crew_by_archetype(
            session, user.discord_id, build.id
        )
        for slot in slots_for_hull(build.hull_class):
            current_crew = aboard_by_archetype.get(slot)
            view.add_item(
                _build_slot_select(
                    build.id, slot, current_crew, eligible_by_archetype.get(slot, [])
                )
            )
    else:
        # Disabled placeholder selects so the View shape stays consistent
        for slot in slots_for_hull(build.hull_class):
            view.add_item(
                HangarSlotSelect(
                    build.id,
                    slot,
                    options=[
                        discord.SelectOption(label="(ship is busy)", value="locked", default=True)
                    ],
                    placeholder=f"{slot.name}: ship locked",
                    disabled=True,
                )
            )

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
) -> HangarSlotSelect:
    options: list[discord.SelectOption] = []
    if not eligible:
        options.append(
            discord.SelectOption(
                label=f"(no eligible {archetype.name.lower()}s)",
                value="none",
                default=True,
            )
        )
        return HangarSlotSelect(build_id, archetype, options=options, disabled=True)

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

    return HangarSlotSelect(build_id, archetype, options=options)
