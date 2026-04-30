"""Discord-agnostic helpers for building/parsing expedition button custom_ids.

Both the bot cog (which renders the persistent View) and the scheduler (which
emits notifications carrying button components) need to agree on this format,
so the format lives here instead of in either consumer.
"""

from __future__ import annotations

import uuid

CUSTOM_ID_PREFIX = "expedition"


def build_custom_id(expedition_id: uuid.UUID, scene_id: str, choice_id: str) -> str:
    return f"{CUSTOM_ID_PREFIX}:{expedition_id}:{scene_id}:{choice_id}"


def parse_custom_id(custom_id: str) -> tuple[uuid.UUID, str, str] | None:
    parts = custom_id.split(":", 3)
    if len(parts) != 4 or parts[0] != CUSTOM_ID_PREFIX:
        return None
    try:
        eid = uuid.UUID(parts[1])
    except ValueError:
        return None
    return (eid, parts[2], parts[3])
