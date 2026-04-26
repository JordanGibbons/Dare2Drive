"""Timer recipe registry — JSON-backed, in-memory lookup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db.models import TimerType

_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "timers"

_FILES: dict[TimerType, str] = {
    TimerType.TRAINING: "training_routines.json",
    TimerType.RESEARCH: "research_projects.json",
    TimerType.SHIP_BUILD: "ship_build_recipes.json",
}


class RecipeNotFound(KeyError):
    """Raised when a recipe id is not present in the registry for a timer type."""


def _load_files() -> dict[TimerType, list[dict[str, Any]]]:
    out: dict[TimerType, list[dict[str, Any]]] = {}
    for ttype, fname in _FILES.items():
        with (_DATA_DIR / fname).open(encoding="utf-8") as f:
            out[ttype] = json.load(f)
    return out


def _build_registry(
    raw: dict[TimerType, list[dict[str, Any]]],
) -> dict[TimerType, dict[str, dict[str, Any]]]:
    """Return {timer_type: {recipe_id: recipe_dict}}, raising on duplicate ids."""
    registry: dict[TimerType, dict[str, dict[str, Any]]] = {}
    for ttype, recipes in raw.items():
        by_id: dict[str, dict[str, Any]] = {}
        for r in recipes:
            rid = r["id"]
            if rid in by_id:
                raise ValueError(f"duplicate recipe id {rid!r} in {ttype.value}")
            by_id[rid] = r
        registry[ttype] = by_id
    return registry


_REGISTRY: dict[TimerType, dict[str, dict[str, Any]]] = _build_registry(_load_files())


def get_recipe(timer_type: TimerType, recipe_id: str) -> dict[str, Any]:
    bucket = _REGISTRY.get(timer_type, {})
    if recipe_id not in bucket:
        raise RecipeNotFound(f"{timer_type.value}/{recipe_id}")
    return bucket[recipe_id]


def list_recipes(timer_type: TimerType) -> list[dict[str, Any]]:
    return list(_REGISTRY.get(timer_type, {}).values())
