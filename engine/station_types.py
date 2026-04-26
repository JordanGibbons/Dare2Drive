"""Station-type registry — JSON-backed, in-memory lookup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db.models import StationType

_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "stations" / "station_types.json"


class StationNotFound(KeyError):
    """Raised when a station id is not present in the registry."""


def _load() -> dict[str, dict[str, Any]]:
    with _DATA_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    by_id: dict[str, dict[str, Any]] = {}
    for s in raw:
        sid = s["id"]
        if sid in by_id:
            raise ValueError(f"duplicate station id {sid!r}")
        by_id[sid] = s
    return by_id


_REGISTRY: dict[str, dict[str, Any]] = _load()


def get_station(station_type: StationType) -> dict[str, Any]:
    return _REGISTRY[station_type.value]


def get_station_by_id(station_id: str) -> dict[str, Any]:
    if station_id not in _REGISTRY:
        raise StationNotFound(station_id)
    return _REGISTRY[station_id]


def list_stations() -> list[dict[str, Any]]:
    return list(_REGISTRY.values())
