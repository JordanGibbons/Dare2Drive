"""Hull-class crew slot composition + lookup helper."""

from __future__ import annotations

import pytest


def test_hull_crew_slots_skirmisher():
    from db.models import CrewArchetype, HullClass
    from engine.class_engine import HULL_CREW_SLOTS

    assert HULL_CREW_SLOTS[HullClass.SKIRMISHER] == [
        CrewArchetype.PILOT,
        CrewArchetype.GUNNER,
    ]


def test_hull_crew_slots_hauler():
    from db.models import CrewArchetype, HullClass
    from engine.class_engine import HULL_CREW_SLOTS

    assert HULL_CREW_SLOTS[HullClass.HAULER] == [
        CrewArchetype.PILOT,
        CrewArchetype.ENGINEER,
        CrewArchetype.NAVIGATOR,
    ]


def test_hull_crew_slots_scout():
    from db.models import CrewArchetype, HullClass
    from engine.class_engine import HULL_CREW_SLOTS

    assert HULL_CREW_SLOTS[HullClass.SCOUT] == [
        CrewArchetype.PILOT,
        CrewArchetype.NAVIGATOR,
    ]


def test_hull_crew_slots_covers_every_hull_class():
    """If a new HullClass is added without a slot config, this test must fail."""
    from db.models import HullClass
    from engine.class_engine import HULL_CREW_SLOTS

    assert set(HULL_CREW_SLOTS.keys()) == set(HullClass)


def test_slots_for_hull_returns_list():
    from db.models import CrewArchetype, HullClass
    from engine.class_engine import slots_for_hull

    slots = slots_for_hull(HullClass.SKIRMISHER)
    assert slots == [CrewArchetype.PILOT, CrewArchetype.GUNNER]


def test_slots_for_hull_unknown_hull_raises():
    """Defense in depth: if someone passes an invalid hull, fail loudly."""
    from engine.class_engine import slots_for_hull

    with pytest.raises((KeyError, TypeError)):
        slots_for_hull("not_a_hull_class")  # type: ignore[arg-type]
