"""DB-level constraint tests for crew_assignments."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from db.models import (
    Build,
    CrewArchetype,
    CrewAssignment,
    CrewMember,
    HullClass,
    Rarity,
    User,
)


@pytest_asyncio.fixture
async def user_with_build(db_session):
    u = User(
        discord_id="333333333",
        username="assigner",
        hull_class=HullClass.SKIRMISHER,
        currency=0,
    )
    db_session.add(u)
    await db_session.flush()
    b = Build(user_id=u.discord_id, name="Test Ship", hull_class=HullClass.SKIRMISHER)
    db_session.add(b)
    await db_session.flush()
    return u, b


@pytest_asyncio.fixture
async def two_pilots(db_session, user_with_build):
    u, _ = user_with_build
    c1 = CrewMember(
        user_id=u.discord_id,
        first_name="A",
        last_name="B",
        callsign="C1",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
    )
    c2 = CrewMember(
        user_id=u.discord_id,
        first_name="D",
        last_name="E",
        callsign="C2",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
    )
    db_session.add_all([c1, c2])
    await db_session.flush()
    return c1, c2


@pytest.mark.asyncio
async def test_unique_build_archetype_constraint(db_session, user_with_build, two_pilots):
    """Two pilots on the same build should error via (build_id, archetype) unique."""
    _, build = user_with_build
    c1, c2 = two_pilots
    db_session.add(CrewAssignment(crew_id=c1.id, build_id=build.id, archetype=CrewArchetype.PILOT))
    await db_session.flush()
    db_session.add(CrewAssignment(crew_id=c2.id, build_id=build.id, archetype=CrewArchetype.PILOT))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_unique_crew_id_constraint(db_session, user_with_build, two_pilots):
    """Same crew on two builds should error via crew_id unique."""
    u, build = user_with_build
    c1, _ = two_pilots
    b2 = Build(user_id=u.discord_id, name="Ship 2", hull_class=HullClass.SKIRMISHER)
    db_session.add(b2)
    await db_session.flush()

    db_session.add(CrewAssignment(crew_id=c1.id, build_id=build.id, archetype=CrewArchetype.PILOT))
    await db_session.flush()
    db_session.add(CrewAssignment(crew_id=c1.id, build_id=b2.id, archetype=CrewArchetype.PILOT))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_cascade_on_crew_delete(db_session, user_with_build, two_pilots):
    """Deleting a crew member cascades to its assignment."""
    from sqlalchemy import select

    _, build = user_with_build
    c1, _ = two_pilots
    db_session.add(CrewAssignment(crew_id=c1.id, build_id=build.id, archetype=CrewArchetype.PILOT))
    await db_session.flush()

    await db_session.delete(c1)
    await db_session.flush()

    result = await db_session.execute(select(CrewAssignment).where(CrewAssignment.crew_id == c1.id))
    assert result.first() is None
