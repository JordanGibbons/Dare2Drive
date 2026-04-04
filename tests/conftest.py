"""Shared test fixtures for Dare2Drive."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


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
            "primary": {"acceleration_scaling": 60, "top_speed_ceiling": 62, "shift_efficiency": 65},
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
            "primary": {"power_boost_pct": 28, "acceleration_boost_pct": 18, "engine_temp_increase": 25},
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
