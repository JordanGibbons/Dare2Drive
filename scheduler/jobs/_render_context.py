"""Shared render-context builder for expedition handlers (event/resolve/complete).

Lives here (not in `engine/`) because it pulls together expedition-side ORM rows
(`ExpeditionCrewAssignment`) — the engine only knows about scenes and outcomes.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Build, CrewMember, Expedition, ExpeditionCrewAssignment


async def build_render_context(session: AsyncSession, expedition: Expedition) -> dict:
    """Assemble the narrative-render context dict from the expedition's build + aboard crew.

    Returns a dict shaped like:
        {
            "ship": {"name": "Flagstaff", "hull": "Skirmisher"},
            "pilot": {"display": '...', "callsign": "Sixgun",
                      "first_name": "Mira", "last_name": "Voss"},
            ...
        }
    Archetypes that aren't aboard simply aren't in the dict; the renderer's
    fallback handles them.
    """
    build = await session.get(Build, expedition.build_id)
    ctx: dict = {
        "ship": {
            "name": build.name if build else "the ship",
            "hull": build.hull_class.name.title() if build and build.hull_class else "",
        }
    }
    rows = (
        await session.execute(
            select(ExpeditionCrewAssignment, CrewMember)
            .join(CrewMember, ExpeditionCrewAssignment.crew_id == CrewMember.id)
            .where(ExpeditionCrewAssignment.expedition_id == expedition.id)
        )
    ).all()
    for assignment, crew in rows:
        archetype_key = assignment.archetype.value  # "pilot", "gunner", etc.
        ctx[archetype_key] = {
            "display": f'{crew.first_name} "{crew.callsign}" {crew.last_name}',
            "callsign": crew.callsign,
            "first_name": crew.first_name,
            "last_name": crew.last_name,
        }
    return ctx
