"""Tests for engine/station_types.py."""

from __future__ import annotations

import pytest

from db.models import StationType


def test_get_station_returns_known():
    from engine.station_types import get_station

    s = get_station(StationType.CARGO_RUN)
    assert s["id"] == "cargo_run"
    assert s["yields_per_tick"]["credits"] == 50
    assert s["preferred_archetype"] == "navigator"


def test_get_station_unknown_raises():
    """Should never happen given enum constraint, but guarded anyway."""
    from engine.station_types import StationNotFound, get_station_by_id

    with pytest.raises(StationNotFound):
        get_station_by_id("no_such_station")


def test_list_stations_returns_all_three():
    from engine.station_types import list_stations

    ids = {s["id"] for s in list_stations()}
    assert ids == {"cargo_run", "repair_bay", "watch_tower"}
