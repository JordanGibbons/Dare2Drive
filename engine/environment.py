"""Environment generation and stat-weight modifiers for races."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config.logging import get_logger

log = get_logger(__name__)

_ENV_FILE = Path(__file__).resolve().parent.parent / "data" / "environments.json"


@dataclass
class EnvironmentCondition:
    """A rolled race environment with stat weight overrides."""

    name: str
    display_name: str
    description: str
    stat_weights: dict[str, float] = field(default_factory=dict)
    variance_multiplier: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "stat_weights": self.stat_weights,
            "variance_multiplier": self.variance_multiplier,
        }


def _load_environments() -> list[dict[str, Any]]:
    """Load environment definitions from JSON."""
    with open(_ENV_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def roll_environment() -> EnvironmentCondition:
    """Randomly select an environment for a race."""
    envs = _load_environments()
    chosen = random.choice(envs)
    env = EnvironmentCondition(
        name=chosen["name"],
        display_name=chosen["display_name"],
        description=chosen["description"],
        stat_weights=chosen["stat_weights"],
        variance_multiplier=chosen.get("variance_multiplier", 1.0),
    )
    log.info("Rolled environment: %s", env.display_name)
    return env


def get_environment_by_name(name: str) -> EnvironmentCondition:
    """Look up a specific environment by name."""
    envs = _load_environments()
    for env_data in envs:
        if env_data["name"] == name:
            return EnvironmentCondition(
                name=env_data["name"],
                display_name=env_data["display_name"],
                description=env_data["description"],
                stat_weights=env_data["stat_weights"],
                variance_multiplier=env_data.get("variance_multiplier", 1.0),
            )
    raise ValueError(f"Unknown environment: {name}")


def apply_environment_weights(
    stats: dict[str, float], environment: EnvironmentCondition
) -> dict[str, float]:
    """
    Apply environment stat weights to a flat stats dictionary.

    Each stat is multiplied by the environment's weight for that stat.
    Missing weights default to 1.0.
    """
    weighted: dict[str, float] = {}
    for stat_name, value in stats.items():
        weight = environment.stat_weights.get(stat_name, 1.0)
        weighted[stat_name] = value * weight
    return weighted
