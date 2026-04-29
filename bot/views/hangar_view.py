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

import discord

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
