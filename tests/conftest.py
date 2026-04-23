"""Shared test fixtures for Dare2Drive."""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
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

    Opens a real connection to the dev database (via Docker) and wraps
    every test in a transaction that is rolled back at teardown so that
    tests never leak rows.

    A fresh engine is created per-fixture invocation to avoid event-loop
    conflicts across tests when using asyncpg connection pools.
    """
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, pool_size=1, max_overflow=0)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        trans = await session.begin()
        try:
            yield session
        finally:
            await trans.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def sample_system(db_session):
    """A persisted System row (rolled back after test)."""
    from db.models import System

    sys = System(
        guild_id="111111111",
        name="Test System",
        owner_discord_id="999999999",
    )
    db_session.add(sys)
    await db_session.flush()
    await db_session.refresh(sys)
    return sys


@pytest_asyncio.fixture
async def sample_sector(db_session, sample_system):
    """A persisted Sector row linked to sample_system (rolled back after test)."""
    from db.models import Sector

    sec = Sector(
        channel_id="222222222",
        system_id=sample_system.guild_id,
        name="Test Sector",
    )
    db_session.add(sec)
    await db_session.flush()
    await db_session.refresh(sec)
    return sec


@pytest.fixture
def sample_engine_card():
    """Return a sample engine card data dict."""
    return {
        "id": str(uuid.uuid4()),
        "name": "Ironforge V8",
        "slot": "engine",
        "rarity": "rare",
        "stats": {
            "primary": {"power": 65, "acceleration": 55, "torque": 68, "max_engine_temp": 78},
            "secondary": {"weight": -22, "durability": 65, "fuel_efficiency": 38},
        },
    }


@pytest.fixture
def sample_transmission_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Quickdraw 6-Speed",
        "slot": "transmission",
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
def sample_tires_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Driftcore Slicks",
        "slot": "tires",
        "rarity": "rare",
        "stats": {
            "primary": {"grip": 62, "handling": 65, "launch_acceleration": 55},
            "secondary": {"durability": 60, "weather_performance": 30, "drag": 5},
        },
    }


@pytest.fixture
def sample_suspension_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Viperstance Adjustables",
        "slot": "suspension",
        "rarity": "rare",
        "stats": {
            "primary": {"handling": 60, "stability": 62, "ride_height_modifier": -10},
            "secondary": {"weight_balance_bonus": 12, "brake_efficiency_scaling": 10},
        },
    }


@pytest.fixture
def sample_chassis_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Phantom Coupe",
        "slot": "chassis",
        "rarity": "rare",
        "stats": {
            "primary": {"drag": -5, "weight": -8, "durability": 65, "style": 65},
            "secondary": {"handling_cap_modifier": 8, "top_speed_multiplier": 1.05},
        },
    }


@pytest.fixture
def sample_turbo_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Blastcore Turbo",
        "slot": "turbo",
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
def sample_brakes_card():
    return {
        "id": str(uuid.uuid4()),
        "name": "Scorchstop Ceramics",
        "slot": "brakes",
        "rarity": "rare",
        "stats": {
            "primary": {"brake_force": 65, "corner_entry_speed": 60, "stability_under_decel": 62},
            "secondary": {"handling_bonus": 12, "durability": 68},
        },
    }


@pytest.fixture
def full_build(
    sample_engine_card,
    sample_transmission_card,
    sample_tires_card,
    sample_suspension_card,
    sample_chassis_card,
    sample_turbo_card,
    sample_brakes_card,
):
    """Return a complete build with all 7 slots filled."""
    cards = {
        sample_engine_card["id"]: sample_engine_card,
        sample_transmission_card["id"]: sample_transmission_card,
        sample_tires_card["id"]: sample_tires_card,
        sample_suspension_card["id"]: sample_suspension_card,
        sample_chassis_card["id"]: sample_chassis_card,
        sample_turbo_card["id"]: sample_turbo_card,
        sample_brakes_card["id"]: sample_brakes_card,
    }
    slots = {
        "engine": sample_engine_card["id"],
        "transmission": sample_transmission_card["id"],
        "tires": sample_tires_card["id"],
        "suspension": sample_suspension_card["id"],
        "chassis": sample_chassis_card["id"],
        "turbo": sample_turbo_card["id"],
        "brakes": sample_brakes_card["id"],
    }
    return {"user_id": "123456789", "slots": slots, "cards": cards}


@pytest.fixture
def empty_build():
    """Return a build with all empty slots."""
    return {
        "user_id": "987654321",
        "slots": {
            "engine": None,
            "transmission": None,
            "tires": None,
            "suspension": None,
            "chassis": None,
            "turbo": None,
            "brakes": None,
        },
        "cards": {},
    }
