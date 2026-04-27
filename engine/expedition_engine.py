"""Expedition event resolver: shared by player-driven and auto-resolve paths.

Public API:
    resolve_scene(session, expedition, scene, picked_choice_id) -> SceneResolution
    select_closing(closings, accumulated_state) -> closing dict
    accumulated_state(expedition) -> {successes, failures, flags}
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Build,
    ExpeditionCrewAssignment,
)
from engine.effect_registry import apply_effect
from engine.stat_namespace import archetype_for_stat, read_stat


class SceneResolution(TypedDict):
    scene_id: str
    choice_id: str | None
    roll: dict | None
    outcome: dict
    auto_resolved: bool


async def _assigned_archetypes(session: AsyncSession, expedition_id: uuid.UUID) -> set[str]:
    """The set of archetype names assigned on this expedition.

    Returns uppercase names (e.g. "PILOT") to match JSON Schema convention.
    """
    result = await session.execute(
        select(ExpeditionCrewAssignment.archetype).where(
            ExpeditionCrewAssignment.expedition_id == expedition_id
        )
    )
    out: set[str] = set()
    for row in result:
        a = row[0]
        if hasattr(a, "name"):
            out.add(a.name)  # use NAME (uppercase) not value (lowercase)
        else:
            out.add(str(a).upper())
    return out


async def _ship_hull_class(session: AsyncSession, build_id: uuid.UUID) -> str:
    """Return the uppercase hull class name for the build (e.g. 'SKIRMISHER')."""
    build = await session.get(Build, build_id)
    if build is None:
        return ""
    hc = build.hull_class
    if hasattr(hc, "name"):
        return hc.name  # uppercase name e.g. "SKIRMISHER"
    return str(hc).upper()


def _filter_visible_choices(
    scene: dict[str, Any],
    assigned_archetypes: set[str],
    ship_hull_class: str,
) -> list[dict[str, Any]]:
    """Drop choices whose `requires` or implicit archetype gate fails."""
    visible: list[dict[str, Any]] = []
    for c in scene.get("choices", []) or []:
        # Default is always visible (validator enforces no requires on default).
        if c.get("default"):
            visible.append(c)
            continue
        req = c.get("requires") or {}
        archetype_required = req.get("archetype")
        if archetype_required and archetype_required not in assigned_archetypes:
            continue
        if "hull_class" in req and req["hull_class"] != ship_hull_class:
            continue
        roll = c.get("roll") or {}
        implicit = archetype_for_stat(roll.get("stat", "")) if roll else None
        if implicit and implicit not in assigned_archetypes:
            continue
        visible.append(c)
    return visible


def _seeded_random(expedition_id: uuid.UUID, scene_id: str) -> float:
    """Deterministic PRNG: same (expedition_id, scene_id) → same float in [0,1)."""
    payload = f"{expedition_id}:{scene_id}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") / (2**64)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


async def resolve_scene(
    session: AsyncSession,
    expedition,
    scene: dict[str, Any],
    picked_choice_id: str | None,
) -> SceneResolution:
    """Resolve one scene.

    If the scene has no choices, applies the scene's outcome and returns.
    If the scene has choices, finds the chosen one (or falls back to default),
    optionally rolls a stat-modified probability, applies the outcome.
    Effect application is idempotent via apply_reward's source_id.
    """
    auto_resolved = picked_choice_id is None
    assigned_archetypes = await _assigned_archetypes(session, expedition.id)
    hull_class = await _ship_hull_class(session, expedition.build_id)

    # Narration-only scene (no choices)
    if not scene.get("choices"):
        outcome = scene.get("outcome", {"narrative": scene.get("narration", ""), "effects": []})
        for eff in outcome.get("effects", []) or []:
            await apply_effect(session, expedition, scene["id"], eff)
        return SceneResolution(
            scene_id=scene["id"],
            choice_id=None,
            roll=None,
            outcome=outcome,
            auto_resolved=auto_resolved,
        )

    visible = _filter_visible_choices(scene, assigned_archetypes, hull_class)
    visible_by_id = {c["id"]: c for c in visible}
    default = next((c for c in visible if c.get("default")), None)
    if default is None:
        raise RuntimeError(f"scene {scene['id']!r} has no default choice")

    if picked_choice_id and picked_choice_id in visible_by_id:
        choice = visible_by_id[picked_choice_id]
    else:
        choice = default

    if "roll" in choice:
        spec = choice["roll"]
        stat_value = await read_stat(session, expedition, spec["stat"])
        if stat_value is None:
            choice = default
        else:
            base_p = spec["base_p"]
            base_stat = spec["base_stat"]
            per_point = spec["per_point"]
            p = base_p + (stat_value - base_stat) * per_point
            p = _clamp(
                p,
                spec.get("clamp_min", 0.05),
                spec.get("clamp_max", 0.95),
            )
            rolled = _seeded_random(expedition.id, scene["id"])
            success = rolled < p
            outcome = choice["outcomes"]["success" if success else "failure"]
            roll_info = {
                "stat": spec["stat"],
                "value": stat_value,
                "p": p,
                "rolled": rolled,
                "success": success,
            }
            for eff in outcome.get("effects", []) or []:
                await apply_effect(session, expedition, scene["id"], eff)
            return SceneResolution(
                scene_id=scene["id"],
                choice_id=choice["id"],
                roll=roll_info,
                outcome=outcome,
                auto_resolved=auto_resolved,
            )

    # Deterministic / no-roll outcome path.
    outcome = choice["outcomes"]["result"]
    for eff in outcome.get("effects", []) or []:
        await apply_effect(session, expedition, scene["id"], eff)
    return SceneResolution(
        scene_id=scene["id"],
        choice_id=choice["id"],
        roll=None,
        outcome=outcome,
        auto_resolved=auto_resolved,
    )


def select_closing(
    closings: list[dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Pick the first matching closing variant. `state` has keys: successes, failures, flags."""
    for c in closings:
        when = c.get("when") or {}
        if when.get("default"):
            return c
        if "min_successes" in when and state["successes"] < when["min_successes"]:
            continue
        if "max_failures" in when and state["failures"] > when["max_failures"]:
            continue
        if "has_flag" in when and when["has_flag"] not in state["flags"]:
            continue
        if "not_flag" in when and when["not_flag"] in state["flags"]:
            continue
        return c
    for c in closings:
        if (c.get("when") or {}).get("default"):
            return c
    raise RuntimeError("no closing matched and no default closing present")


def accumulated_state(expedition) -> dict[str, Any]:
    """Walk expedition.scene_log and compute {successes, failures, flags}."""
    successes = 0
    failures = 0
    flags: set[str] = set()
    for entry in expedition.scene_log or []:
        if entry.get("kind") == "flag":
            flags.add(entry.get("name"))
            continue
        if entry.get("status") == "resolved":
            roll = entry.get("roll") or {}
            if roll:
                if roll.get("success"):
                    successes += 1
                else:
                    failures += 1
            else:
                successes += 1
    return {"successes": successes, "failures": failures, "flags": flags}
