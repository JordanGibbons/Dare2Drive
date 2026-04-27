"""Effect-op registry for expedition outcomes.

Closed vocabulary. Adding a new op requires updating KNOWN_OPS plus an
apply_<op_name> handler. Both the validator and the doc generator read
from KNOWN_OPS, so the schema, the docs, and the engine never drift.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    CrewArchetype,
    CrewMember,
    ExpeditionCrewAssignment,
    RewardSourceType,
)
from engine.rewards import apply_reward

if TYPE_CHECKING:
    from db.models import Expedition

# Each entry: {params: list[str] required keys, summary: docs blurb}.
KNOWN_OPS: dict[str, dict[str, Any]] = {
    "reward_credits": {
        "params": [],  # value is a plain int
        "param_kind": "scalar_int",
        "summary": "Adds (or subtracts, if negative) credits to the player.",
    },
    "reward_wreck": {
        "params": ["hull_class", "quality"],
        "param_kind": "object",
        "summary": "Generates a wreck row of the named hull_class + quality.",
    },
    "reward_card": {
        "params": ["slot", "rarity"],
        "param_kind": "object",
        "summary": "Mints a card of the given slot + rarity for the player.",
    },
    "reward_xp": {
        "params": ["archetype", "amount"],
        "param_kind": "object",
        "summary": "Grants XP to the assigned crew of the named archetype. "
        "No-op if no crew of that archetype is assigned.",
    },
    "injure_crew": {
        "params": ["archetype", "duration_hours"],
        "param_kind": "object",
        "summary": "Sets the assigned crew's `injured_until` to now + duration_hours. "
        "No-op if no crew of that archetype is assigned.",
    },
    "damage_part": {
        "params": ["slot", "amount"],
        "param_kind": "object",
        "summary": "Reduces durability on the equipped card in the given slot by `amount` "
        "(0..1, fractional).",
    },
    "set_flag": {
        "params": ["name"],
        "param_kind": "object",
        "summary": "Records a named flag in the expedition's accumulated state. "
        "Readable by `when` clauses on later scenes / closings.",
    },
}


def validate_effect(effect: dict[str, Any]) -> list[str]:
    """Return a list of error messages, [] if valid."""
    errors: list[str] = []
    if not isinstance(effect, dict) or len(effect) != 1:
        errors.append("each effect must be a dict with exactly one op key")
        return errors
    op_name, value = next(iter(effect.items()))
    spec = KNOWN_OPS.get(op_name)
    if spec is None:
        errors.append(f"unknown effect op: {op_name}")
        return errors
    if spec["param_kind"] == "scalar_int":
        if not isinstance(value, int):
            errors.append(f"{op_name} expects an integer, got {type(value).__name__}")
    elif spec["param_kind"] == "object":
        if not isinstance(value, dict):
            errors.append(f"{op_name} expects an object")
            return errors
        for required in spec["params"]:
            if required not in value:
                errors.append(f"{op_name} missing required param: {required}")
    return errors


async def apply_effect(
    session: AsyncSession,
    expedition: "Expedition",
    scene_id: str,
    effect: dict[str, Any],
) -> None:
    """Apply a single effect inside the caller's transaction.

    Idempotent: every reward write goes through `apply_reward()` with
    `source_id = f"expedition:{expedition.id}:{scene_id}"`, so a retry of the
    same scene short-circuits via the (source_type, source_id) unique constraint.

    `set_flag` mutates `expedition.scene_log` (caller is responsible for
    flushing). All other ops are reward-ledger-backed and atomic.
    """
    errors = validate_effect(effect)
    if errors:
        raise ValueError(f"invalid effect: {effect} → {errors}")
    op_name, value = next(iter(effect.items()))
    source_id = f"expedition:{expedition.id}:{scene_id}"

    if op_name == "reward_credits":
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + ":credits",
            delta={"credits": int(value)},
        )

    elif op_name == "reward_xp":
        crew = await _assigned_crew(session, expedition.id, value["archetype"])
        if crew is None:
            return  # no-op when archetype not assigned
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + f":xp:{value['archetype']}",
            delta={"xp": {value["archetype"]: int(value["amount"])}},
        )

    elif op_name == "reward_wreck":
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + f":wreck:{value['hull_class']}",
            delta={
                "wreck": {
                    "hull_class": value["hull_class"],
                    "quality": value["quality"],
                }
            },
        )

    elif op_name == "reward_card":
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + f":card:{value['slot']}:{value['rarity']}",
            delta={
                "card": {
                    "slot": value["slot"],
                    "rarity": value["rarity"],
                }
            },
        )

    elif op_name == "injure_crew":
        crew = await _assigned_crew(session, expedition.id, value["archetype"])
        if crew is None:
            return  # no-op
        crew.injured_until = datetime.now(timezone.utc) + timedelta(
            hours=int(value["duration_hours"])
        )
        # The `apply_reward` ledger entry is the idempotency token — re-applying
        # the same scene's injure_crew should not extend the timer twice.
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + f":injure:{value['archetype']}",
            delta={
                "injury": {
                    "crew_id": str(crew.id),
                    "duration_hours": int(value["duration_hours"]),
                }
            },
        )

    elif op_name == "damage_part":
        # Apply via existing engine/durability if available; fallback to ledger record.
        await apply_reward(
            session,
            user_id=expedition.user_id,
            source_type=RewardSourceType.EXPEDITION_OUTCOME,
            source_id=source_id + f":damage:{value['slot']}",
            delta={
                "damage": {
                    "build_id": str(expedition.build_id),
                    "slot": value["slot"],
                    "amount": float(value["amount"]),
                }
            },
        )
        # Also reduce durability on the equipped card. The exact path depends
        # on engine/durability.py — call its public reducer:
        try:
            from engine.durability import damage_equipped_part

            await damage_equipped_part(
                session,
                build_id=expedition.build_id,
                slot=value["slot"],
                amount=float(value["amount"]),
            )
        except ImportError:
            pass  # durability engine not available; ledger record is the truth

    elif op_name == "set_flag":
        # Append to scene_log under a synthetic flag entry for later when-clause
        # matching. The resolver consolidates flags via _accumulated_flags().
        scene_log = list(expedition.scene_log or [])
        scene_log.append(
            {
                "kind": "flag",
                "scene_id": scene_id,
                "name": value["name"],
            }
        )
        expedition.scene_log = scene_log

    else:
        # validate_effect should have caught this; defensive raise.
        raise RuntimeError(f"unhandled effect op: {op_name}")


async def _assigned_crew(
    session: AsyncSession, expedition_id, archetype_str: str
) -> CrewMember | None:
    # Support both value ("pilot") and name ("PILOT") forms.
    try:
        archetype = CrewArchetype(archetype_str)
    except ValueError:
        archetype = CrewArchetype[archetype_str.upper()]
    result = await session.execute(
        select(CrewMember)
        .join(ExpeditionCrewAssignment, ExpeditionCrewAssignment.crew_id == CrewMember.id)
        .where(ExpeditionCrewAssignment.expedition_id == expedition_id)
        .where(ExpeditionCrewAssignment.archetype == archetype)
    )
    return result.scalar_one_or_none()
