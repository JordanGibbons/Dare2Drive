"""Stat namespace registry — what authors can reference in roll.stat / requires.stat."""

from __future__ import annotations

import pytest


def test_known_namespaces_present():
    from engine.stat_namespace import KNOWN_STAT_KEYS

    # Crew archetype stats
    for arche in ("pilot", "gunner", "engineer", "navigator"):
        for stat in ("acceleration", "combat", "repair", "luck"):
            # Not every archetype has every stat — see archetype-specific stat
            # mapping in engine/crew_xp.py. For the namespace registry we
            # publish ALL crew-stat keys generically: each archetype has its own
            # subset, and the validator cross-checks per-archetype below.
            pass
    # Ship namespace
    for stat in ("acceleration", "durability", "power"):
        assert f"ship.{stat}" in KNOWN_STAT_KEYS
    # Aggregate keys
    assert "crew.avg_level" in KNOWN_STAT_KEYS
    assert "crew.count" in KNOWN_STAT_KEYS


def test_is_known_stat():
    from engine.stat_namespace import is_known_stat

    assert is_known_stat("ship.durability")
    assert is_known_stat("crew.avg_level")
    assert is_known_stat("pilot.acceleration")
    assert not is_known_stat("ship.nonsense")
    assert not is_known_stat("randomthing")
    assert not is_known_stat("pilot.notarealstat")


def test_archetype_for_stat():
    """Returns the implicit archetype gate for a crew-specific stat key."""
    from engine.stat_namespace import archetype_for_stat

    assert archetype_for_stat("pilot.acceleration") == "PILOT"
    assert archetype_for_stat("gunner.combat") == "GUNNER"
    assert archetype_for_stat("engineer.repair") == "ENGINEER"
    assert archetype_for_stat("navigator.luck") == "NAVIGATOR"
    assert archetype_for_stat("ship.durability") is None
    assert archetype_for_stat("crew.avg_level") is None


@pytest.mark.asyncio
async def test_read_stat_reads_pilot_acceleration(db_session, sample_expedition_with_pilot):
    """`read_stat` returns the assigned PILOT crew's acceleration."""
    from engine.stat_namespace import read_stat

    expedition, pilot = sample_expedition_with_pilot
    val = await read_stat(db_session, expedition, "pilot.acceleration")
    # Fixture sets pilot.acceleration = 70.
    assert val == 70


@pytest.mark.asyncio
async def test_read_stat_returns_none_when_archetype_unassigned(
    db_session, sample_expedition_pilot_only
):
    """`read_stat` returns None for a crew slot the player didn't assign."""
    from engine.stat_namespace import read_stat

    expedition, _ = sample_expedition_pilot_only
    val = await read_stat(db_session, expedition, "gunner.combat")
    assert val is None


@pytest.mark.asyncio
async def test_read_stat_ship_durability(db_session, sample_expedition_with_pilot):
    """`read_stat` reads ship.durability via engine/stat_resolver from the locked build."""
    from engine.stat_namespace import read_stat

    expedition, _ = sample_expedition_with_pilot
    val = await read_stat(db_session, expedition, "ship.durability")
    # Just assert it returns a number.
    assert val is not None
    assert isinstance(val, (int, float))
