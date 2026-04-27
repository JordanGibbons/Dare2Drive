"""Effect-op registry — closed vocabulary of expedition outcome operations."""

from __future__ import annotations

import pytest


def test_known_effect_ops_present():
    from engine.effect_registry import KNOWN_OPS

    expected = {
        "reward_credits",
        "reward_wreck",
        "reward_card",
        "reward_xp",
        "injure_crew",
        "damage_part",
        "set_flag",
    }
    assert expected <= set(KNOWN_OPS.keys())


def test_each_op_declares_required_params():
    """Every op has a parameter schema used by the validator."""
    from engine.effect_registry import KNOWN_OPS

    for name, spec in KNOWN_OPS.items():
        assert "params" in spec, f"{name} missing 'params'"
        assert "summary" in spec, f"{name} missing 'summary'"


def test_validate_effect_accepts_known_op():
    from engine.effect_registry import validate_effect

    errors = validate_effect({"reward_credits": 250})
    assert errors == []


def test_validate_effect_rejects_unknown_op():
    from engine.effect_registry import validate_effect

    errors = validate_effect({"reward_telepathy": True})
    assert len(errors) == 1
    assert "unknown effect op" in errors[0].lower()


def test_validate_effect_rejects_multi_op():
    """An effect must be exactly one op."""
    from engine.effect_registry import validate_effect

    errors = validate_effect({"reward_credits": 100, "set_flag": {"name": "x"}})
    assert any("exactly one" in e.lower() for e in errors)


def test_validate_effect_param_shape_injure_crew():
    from engine.effect_registry import validate_effect

    assert validate_effect({"injure_crew": {"archetype": "GUNNER", "duration_hours": 24}}) == []
    errs = validate_effect({"injure_crew": {"archetype": "GUNNER"}})
    assert any("duration_hours" in e for e in errs)


@pytest.mark.asyncio
async def test_apply_reward_credits_writes_ledger(db_session, sample_expedition_with_pilot):
    from engine.effect_registry import apply_effect

    expedition, _ = sample_expedition_with_pilot
    await apply_effect(
        db_session,
        expedition,
        scene_id="test_scene",
        effect={"reward_credits": 250},
    )
    from sqlalchemy import select

    from db.models import RewardLedger, RewardSourceType

    rows = (
        (
            await db_session.execute(
                select(RewardLedger)
                .where(RewardLedger.user_id == expedition.user_id)
                .where(RewardLedger.source_type == RewardSourceType.EXPEDITION_OUTCOME)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].delta.get("credits") == 250


@pytest.mark.asyncio
async def test_apply_effect_idempotent_on_double_call(db_session, sample_expedition_with_pilot):
    from engine.effect_registry import apply_effect

    expedition, _ = sample_expedition_with_pilot
    await apply_effect(
        db_session,
        expedition,
        scene_id="test_scene_idem",
        effect={"reward_credits": 100},
    )
    await apply_effect(
        db_session,
        expedition,
        scene_id="test_scene_idem",
        effect={"reward_credits": 100},
    )
    from sqlalchemy import func, select

    from db.models import RewardLedger

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(RewardLedger)
            .where(RewardLedger.user_id == expedition.user_id)
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_apply_effect_reward_xp_adds_to_assigned_crew(
    db_session, sample_expedition_with_pilot
):
    """reward_xp increments the assigned crew's xp."""
    from db.models import CrewMember
    from engine.effect_registry import apply_effect

    expedition, pilot = sample_expedition_with_pilot
    initial_xp = pilot.xp or 0
    await apply_effect(
        db_session,
        expedition,
        scene_id="xp_test",
        effect={"reward_xp": {"archetype": "PILOT", "amount": 250}},
    )
    refreshed = await db_session.get(CrewMember, pilot.id)
    assert refreshed.xp == initial_xp + 250


@pytest.mark.asyncio
async def test_apply_effect_reward_xp_noop_when_archetype_unassigned(
    db_session, sample_expedition_with_pilot
):
    """reward_xp on an unassigned archetype is a no-op (no error)."""
    from engine.effect_registry import apply_effect

    expedition, pilot = sample_expedition_with_pilot
    initial_xp = pilot.xp or 0
    await apply_effect(
        db_session,
        expedition,
        scene_id="xp_test_noop",
        effect={"reward_xp": {"archetype": "GUNNER", "amount": 250}},
    )
    # No GUNNER assigned → no exception, no XP change for the PILOT.
    from db.models import CrewMember

    refreshed = await db_session.get(CrewMember, pilot.id)
    assert refreshed.xp == initial_xp


@pytest.mark.asyncio
async def test_apply_effect_injure_crew_sets_injured_until(
    db_session, sample_expedition_with_pilot
):
    from datetime import datetime, timezone

    from db.models import CrewMember
    from engine.effect_registry import apply_effect

    expedition, pilot = sample_expedition_with_pilot
    await apply_effect(
        db_session,
        expedition,
        scene_id="injury_test",
        effect={"injure_crew": {"archetype": "PILOT", "duration_hours": 24}},
    )
    refreshed = await db_session.get(CrewMember, pilot.id)
    assert refreshed.injured_until is not None
    delta = refreshed.injured_until - datetime.now(timezone.utc)
    assert 23 < delta.total_seconds() / 3600 < 25
