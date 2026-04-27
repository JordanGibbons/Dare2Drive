"""Shared test fixtures for Dare2Drive."""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
import redis.asyncio as _redis_async
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Async DB session fixture (for Tasks 16-18 and future DB-backed tests).
# Uses localhost so tests run from the host machine can reach the docker DB.
# ---------------------------------------------------------------------------

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://dare2drive:dare2drive@localhost:5432/dare2drive",
)


@pytest_asyncio.fixture
async def db_session():
    """Async DB session with per-test rollback isolation.

    Uses a connection-level transaction with `join_transaction_mode="create_savepoint"`
    so that production code calling `session.commit()` translates to a SAVEPOINT release
    rather than finalizing the outer transaction. The outer transaction is rolled back
    at teardown, undoing all writes regardless of inner commits.
    """
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, pool_size=1, max_overflow=0)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with session_factory() as session:
            try:
                yield session
            finally:
                if trans.is_active:
                    await trans.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def sample_sector(db_session):
    """A persisted Sector row (rolled back after test)."""
    from db.models import Sector

    sys = Sector(
        guild_id="111111111",
        name="Test Sector",
        owner_discord_id="999999999",
    )
    db_session.add(sys)
    await db_session.flush()
    await db_session.refresh(sys)
    return sys


@pytest_asyncio.fixture
async def sample_system(db_session, sample_sector):
    """A persisted System row linked to sample_sector (rolled back after test)."""
    from db.models import System

    sec = System(
        channel_id="222222222",
        sector_id=sample_sector.guild_id,
        name="Test System",
    )
    db_session.add(sec)
    await db_session.flush()
    await db_session.refresh(sec)
    return sec


@pytest.fixture
def sample_reactor_card():
    """Return a sample reactor card data dict."""
    return {
        "id": str(uuid.uuid4()),
        "name": "Ironforge Reactor",
        "slot": "reactor",
        "rarity": "rare",
        "stats": {
            "primary": {"power": 65, "acceleration": 55, "torque": 68, "max_reactor_temp": 78},
            "secondary": {"weight": -22, "durability": 65, "fuel_efficiency": 38},
        },
    }


@pytest.fixture
def sample_drive_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Quickdraw Drive",
        "slot": "drive",
        "rarity": "rare",
        "stats": {
            "primary": {
                "acceleration_scaling": 60,
                "top_speed_ceiling": 62,
                "shift_efficiency": 65,
            },
            "secondary": {"durability": 68, "torque_transfer_pct": 72},
        },
    }


@pytest.fixture
def sample_thrusters_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Driftcore Thrusters",
        "slot": "thrusters",
        "rarity": "rare",
        "stats": {
            "primary": {"grip": 62, "handling": 65, "launch_acceleration": 55},
            "secondary": {"durability": 60, "weather_performance": 30, "drag": 5},
        },
    }


@pytest.fixture
def sample_stabilizers_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Viperstance Stabilizers",
        "slot": "stabilizers",
        "rarity": "rare",
        "stats": {
            "primary": {"handling": 60, "stability": 62, "ride_height_modifier": -10},
            "secondary": {"weight_balance_bonus": 12, "brake_efficiency_scaling": 10},
        },
    }


@pytest.fixture
def sample_hull_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Phantom Hull",
        "slot": "hull",
        "rarity": "rare",
        "stats": {
            "primary": {"drag": -5, "weight": -8, "durability": 65, "style": 65},
            "secondary": {"handling_cap_modifier": 8, "top_speed_multiplier": 1.05},
        },
    }


@pytest.fixture
def sample_overdrive_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Blastcore Overdrive",
        "slot": "overdrive",
        "rarity": "rare",
        "stats": {
            "primary": {
                "power_boost_pct": 28,
                "acceleration_boost_pct": 18,
                "engine_temp_increase": 25,
            },
            "secondary": {"durability": 65, "torque_spike_modifier": 18},
        },
    }


@pytest.fixture
def sample_retros_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Scorchstop Retros",
        "slot": "retros",
        "rarity": "rare",
        "stats": {
            "primary": {"brake_force": 65, "corner_entry_speed": 60, "stability_under_decel": 62},
            "secondary": {"handling_bonus": 12, "durability": 68},
        },
    }


@pytest.fixture
def full_build(
    sample_reactor_card,
    sample_drive_card,
    sample_thrusters_card,
    sample_stabilizers_card,
    sample_hull_card,
    sample_overdrive_card,
    sample_retros_card,
):
    """Return a complete build with all 7 slots filled."""
    cards = {
        sample_reactor_card["id"]: sample_reactor_card,
        sample_drive_card["id"]: sample_drive_card,
        sample_thrusters_card["id"]: sample_thrusters_card,
        sample_stabilizers_card["id"]: sample_stabilizers_card,
        sample_hull_card["id"]: sample_hull_card,
        sample_overdrive_card["id"]: sample_overdrive_card,
        sample_retros_card["id"]: sample_retros_card,
    }
    slots = {
        "reactor": sample_reactor_card["id"],
        "drive": sample_drive_card["id"],
        "thrusters": sample_thrusters_card["id"],
        "stabilizers": sample_stabilizers_card["id"],
        "hull": sample_hull_card["id"],
        "overdrive": sample_overdrive_card["id"],
        "retros": sample_retros_card["id"],
    }
    return {"user_id": "123456789", "slots": slots, "cards": cards}


@pytest.fixture
def empty_build():
    """Return a build with all empty slots."""
    return {
        "user_id": "987654321",
        "slots": {
            "reactor": None,
            "drive": None,
            "thrusters": None,
            "stabilizers": None,
            "hull": None,
            "overdrive": None,
            "retros": None,
        },
        "cards": {},
    }


_TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")


@pytest_asyncio.fixture
async def redis_client():
    """Async Redis client pointed at db 15 (test isolation)."""
    client = _redis_async.from_url(_TEST_REDIS_URL, decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


# ---------------------------------------------------------------------------
# Cog-side helper: wraps the savepoint-isolated `db_session` so production code
# that does `async with async_session() as s, s.begin():` can run inside the
# test's already-open transaction. `.begin()` is rerouted to `.begin_nested()`.
# ---------------------------------------------------------------------------


class SessionProxy:
    """Forward attribute access to the wrapped session, but route .begin() to .begin_nested()."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def begin(self):
        return self._session.begin_nested()


class SessionWrapper:
    """Yield a SessionProxy around the test's db_session as an async context manager."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return SessionProxy(self._session)

    async def __aexit__(self, *a):
        return False


# ---------------------------------------------------------------------------
# Phase 2b: Expedition fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sample_expedition_with_pilot(db_session, sample_system):
    """An ACTIVE expedition with a PILOT crew member assigned (acceleration=70)."""
    import uuid
    from datetime import datetime, timedelta, timezone

    from db.models import (
        Build,
        BuildActivity,
        CrewActivity,
        CrewArchetype,
        CrewMember,
        Expedition,
        ExpeditionCrewAssignment,
        ExpeditionState,
        HullClass,
        Rarity,
        User,
    )

    user = User(
        discord_id="exp_test_user_1",
        username="exp1",
        hull_class=HullClass.SKIRMISHER,
        currency=1000,
    )
    db_session.add(user)
    await db_session.flush()

    build = Build(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.ON_EXPEDITION,
    )
    db_session.add(build)
    await db_session.flush()

    pilot = CrewMember(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
        stats={"acceleration": 70, "luck": 40},
        current_activity=CrewActivity.ON_EXPEDITION,
    )
    db_session.add(pilot)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    expedition = Expedition(
        id=uuid.uuid4(),
        user_id=user.discord_id,
        build_id=build.id,
        template_id="outer_marker_patrol",
        state=ExpeditionState.ACTIVE,
        started_at=now,
        completes_at=now + timedelta(hours=6),
        correlation_id=uuid.uuid4(),
        scene_log=[],
    )
    db_session.add(expedition)
    await db_session.flush()
    db_session.add(
        ExpeditionCrewAssignment(
            expedition_id=expedition.id,
            crew_id=pilot.id,
            archetype=CrewArchetype.PILOT,
        )
    )
    await db_session.flush()
    build.current_activity_id = expedition.id
    pilot.current_activity_id = expedition.id
    await db_session.flush()
    return expedition, pilot


@pytest_asyncio.fixture
async def sample_expedition_pilot_only(sample_expedition_with_pilot):
    """Alias — fixture above already has only a PILOT, no GUNNER."""
    return sample_expedition_with_pilot


@pytest_asyncio.fixture
async def sample_user(db_session):
    """A persisted User row with a unique discord_id (rolled back after test)."""
    from db.models import HullClass, User

    discord_id = f"sampleuser_{uuid.uuid4().hex[:8]}"
    u = User(
        discord_id=discord_id,
        username=f"user_{discord_id}",
        hull_class=HullClass.SKIRMISHER,
        currency=1000,
    )
    db_session.add(u)
    await db_session.flush()
    return u
