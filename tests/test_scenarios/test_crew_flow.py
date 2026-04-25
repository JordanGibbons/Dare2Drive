"""End-to-end: recruit → assign → race → XP gained → level-up triggers higher boost."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from db.models import (
    Build,
    CrewAssignment,
    CrewMember,
    HullClass,
    User,
)


@pytest_asyncio.fixture
async def full_player(db_session):
    u = User(
        discord_id="444111111",
        username="fullpath",
        hull_class=HullClass.SKIRMISHER,
        currency=5000,
    )
    db_session.add(u)
    await db_session.flush()
    build = Build(
        user_id=u.discord_id,
        name="Flagship",
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add(build)
    await db_session.flush()
    return u, build


@pytest.mark.asyncio
async def test_recruit_assign_race_xp_level_up(full_player, db_session):
    from engine.crew_recruit import recruit_crew_from_dossier
    from engine.crew_xp import award_xp, xp_for_next

    user, build = full_player

    member = await recruit_crew_from_dossier(db_session, user, "recruit_lead")
    await db_session.flush()

    # Assign
    db_session.add(
        CrewAssignment(
            crew_id=member.id,
            build_id=build.id,
            archetype=member.archetype,
        )
    )
    await db_session.flush()

    # Simulate a race that grants XP to hit L2
    threshold_xp = xp_for_next(1)
    leveled = award_xp(member, threshold_xp)
    assert leveled is True
    assert member.level == 2

    # Crew query by build_id returns the assigned member at L2
    res = await db_session.execute(
        select(CrewMember)
        .join(CrewAssignment, CrewAssignment.crew_id == CrewMember.id)
        .where(CrewAssignment.build_id == build.id)
    )
    crew = list(res.scalars().all())
    assert len(crew) == 1
    assert crew[0].level == 2


@pytest.mark.asyncio
async def test_same_build_with_vs_without_crew_produces_different_stats(full_build):
    """Identical build dict, different crew lists → different placement scores in compute_race."""
    import random

    from engine.environment import EnvironmentCondition
    from engine.race_engine import compute_race

    def _crew(arch, rarity, lvl=1):
        m = MagicMock()
        m.archetype = MagicMock(value=arch)
        m.rarity = MagicMock(value=rarity)
        m.level = lvl
        return m

    with_crew = {**full_build, "crew": [_crew("pilot", "legendary", 5)]}
    without_crew = {
        **full_build,
        "user_id": full_build["user_id"] + "x",
        "crew": [],
    }

    env = EnvironmentCondition(
        name="clear",
        display_name="Clear",
        description="Test environment",
        stat_weights={
            k: 1.0
            for k in [
                "power",
                "handling",
                "top_speed",
                "grip",
                "braking",
                "durability",
                "acceleration",
                "stability",
                "weather_performance",
            ]
        },
        variance_multiplier=0.0,
    )
    random.seed(7)
    r = compute_race([with_crew, without_crew], environment=env)
    scores = {p.user_id: p.score for p in r.placements}
    assert scores[with_crew["user_id"]] > scores[without_crew["user_id"]]
