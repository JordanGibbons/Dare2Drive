"""Phase 2c — ORM-shape tests for BuildCrewAssignment."""

from __future__ import annotations

import uuid

import pytest


def test_build_crew_assignment_columns():
    from db.models import BuildCrewAssignment

    cols = {c.name for c in BuildCrewAssignment.__table__.columns}
    assert cols >= {"build_id", "crew_id", "archetype", "assigned_at"}


def test_build_crew_assignment_pk_is_build_archetype():
    from db.models import BuildCrewAssignment

    pk_cols = {c.name for c in BuildCrewAssignment.__table__.primary_key.columns}
    assert pk_cols == {"build_id", "archetype"}


def test_build_crew_assignment_unique_crew_id_constraint():
    from db.models import BuildCrewAssignment

    constraints = BuildCrewAssignment.__table__.constraints
    unique_single_columns = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("crew_id",) in unique_single_columns


@pytest.mark.asyncio
async def test_build_crew_assignment_unique_crew_id_enforced(db_session, sample_user):
    """The DB-level UNIQUE(crew_id) trips when the same crew is inserted for two builds."""
    from db.models import (
        Build,
        BuildCrewAssignment,
        CrewArchetype,
        CrewMember,
        HullClass,
        Rarity,
    )

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=1,
    )
    build_a = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
    )
    build_b = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Wanderer",
        hull_class=HullClass.HAULER,
    )
    db_session.add_all([crew, build_a, build_b])
    await db_session.flush()

    db_session.add(
        BuildCrewAssignment(build_id=build_a.id, crew_id=crew.id, archetype=CrewArchetype.PILOT)
    )
    await db_session.flush()  # first assignment OK

    db_session.add(
        BuildCrewAssignment(build_id=build_b.id, crew_id=crew.id, archetype=CrewArchetype.PILOT)
    )
    with pytest.raises(Exception) as exc_info:
        await db_session.flush()
    assert (
        "uq_build_crew_assignments_crew_id" in str(exc_info.value).lower()
        or "unique" in str(exc_info.value).lower()
    )
