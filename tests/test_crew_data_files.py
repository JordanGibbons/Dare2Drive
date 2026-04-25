"""Validate shape + coverage of Phase 1 crew data files."""

from __future__ import annotations

import json
from pathlib import Path

from db.models import CrewArchetype, Rarity

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "crew"


def _load(name: str) -> dict:
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


BUILD_STATS_FIELDS = {
    "effective_power",
    "effective_handling",
    "effective_top_speed",
    "effective_grip",
    "effective_braking",
    "effective_durability",
    "effective_acceleration",
    "effective_stability",
    "effective_weather_performance",
}


def test_archetypes_covers_all_five_and_valid_stats():
    data = _load("archetypes.json")
    assert set(data.keys()) == {a.value for a in CrewArchetype}
    for arch, mapping in data.items():
        assert set(mapping.keys()) == {"primary", "secondary"}
        assert mapping["primary"] in BUILD_STATS_FIELDS
        assert mapping["secondary"] in BUILD_STATS_FIELDS


def test_rarity_boosts_covers_all_rarities_as_floats():
    data = _load("rarity_boosts.json")
    assert set(data.keys()) == {r.value for r in Rarity}
    for rarity, val in data.items():
        assert isinstance(val, (int, float))
        assert 0 < val < 1  # sanity: boost is a sub-unity fraction


def test_dossier_tables_has_three_tiers_with_correct_shape():
    data = _load("dossier_tables.json")
    assert set(data.keys()) == {"recruit_lead", "dossier", "elite_dossier"}
    for tier, cfg in data.items():
        assert set(cfg.keys()) >= {"display_name", "flavor", "size", "price", "weights"}
        assert cfg["size"] == 1
        assert isinstance(cfg["price"], int) and cfg["price"] > 0
        assert set(cfg["weights"].keys()) == {r.value for r in Rarity}


def test_name_pool_has_three_lists_each_nonempty():
    data = _load("name_pool.json")
    assert set(data.keys()) >= {"first_names", "last_names", "callsigns"}
    for key in ("first_names", "last_names", "callsigns"):
        assert isinstance(data[key], list)
        assert len(data[key]) >= 60, f"{key} must have at least 60 entries"
