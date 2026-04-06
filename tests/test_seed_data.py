"""Tests for seed data JSON integrity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CARDS_DIR = DATA_DIR / "cards"

SLOT_FILES = {
    "engines.json": "engine",
    "transmissions.json": "transmission",
    "tires.json": "tires",
    "suspension.json": "suspension",
    "chassis.json": "chassis",
    "turbos.json": "turbo",
    "brakes.json": "brakes",
}

EXPECTED_STAT_SCHEMAS = {
    "engine": {
        "primary": {"power", "acceleration", "torque", "max_engine_temp"},
        "secondary": {"weight", "durability", "fuel_efficiency"},
    },
    "transmission": {
        "primary": {"acceleration_scaling", "top_speed_ceiling", "shift_efficiency"},
        "secondary": {"durability", "torque_transfer_pct"},
    },
    "tires": {
        "primary": {"grip", "handling", "launch_acceleration"},
        "secondary": {"durability", "weather_performance", "drag"},
    },
    "suspension": {
        "primary": {"handling", "stability", "ride_height_modifier"},
        "secondary": {"weight_balance_bonus", "brake_efficiency_scaling"},
    },
    "chassis": {
        "primary": {"drag", "weight", "durability", "style"},
        "secondary": {"handling_cap_modifier", "top_speed_multiplier"},
    },
    "turbo": {
        "primary": {"power_boost_pct", "acceleration_boost_pct", "engine_temp_increase"},
        "secondary": {"durability", "torque_spike_modifier"},
    },
    "brakes": {
        "primary": {"brake_force", "corner_entry_speed", "stability_under_decel"},
        "secondary": {"handling_bonus", "durability"},
    },
}

VALID_RARITIES = {"common", "uncommon", "rare", "epic", "legendary", "ghost"}


class TestCardDataIntegrity:
    @pytest.mark.parametrize("filename,expected_slot", SLOT_FILES.items())
    def test_json_is_valid(self, filename, expected_slot):
        path = CARDS_DIR / filename
        assert path.exists(), f"Missing {filename}"
        with open(path) as f:
            cards = json.load(f)
        assert isinstance(cards, list)
        assert len(cards) >= 3, f"{filename} should have at least 3 cards"

    @pytest.mark.parametrize("filename,expected_slot", SLOT_FILES.items())
    def test_cards_have_correct_slot(self, filename, expected_slot):
        with open(CARDS_DIR / filename) as f:
            cards = json.load(f)
        for card in cards:
            assert card["slot"] == expected_slot, f"{card['name']} has wrong slot"

    @pytest.mark.parametrize("filename,expected_slot", SLOT_FILES.items())
    def test_cards_have_valid_rarity(self, filename, expected_slot):
        with open(CARDS_DIR / filename) as f:
            cards = json.load(f)
        for card in cards:
            assert card["rarity"] in VALID_RARITIES, f"{card['name']} has invalid rarity"

    @pytest.mark.parametrize("filename,expected_slot", SLOT_FILES.items())
    def test_cards_have_correct_stat_schema(self, filename, expected_slot):
        with open(CARDS_DIR / filename) as f:
            cards = json.load(f)
        schema = EXPECTED_STAT_SCHEMAS[expected_slot]
        for card in cards:
            stats = card["stats"]
            primary_keys = set(stats.get("primary", {}).keys())
            secondary_keys = set(stats.get("secondary", {}).keys())
            assert (
                primary_keys == schema["primary"]
            ), f"{card['name']} primary stats mismatch: {primary_keys} != {schema['primary']}"
            assert (
                secondary_keys == schema["secondary"]
            ), f"{card['name']} secondary stats mismatch: {secondary_keys} != {schema['secondary']}"

    @pytest.mark.parametrize("filename,expected_slot", SLOT_FILES.items())
    def test_legendary_cards_have_print_max_500(self, filename, expected_slot):
        with open(CARDS_DIR / filename) as f:
            cards = json.load(f)
        for card in cards:
            if card["rarity"] == "legendary":
                assert card.get("print_max") == 500, f"{card['name']} should have print_max=500"

    @pytest.mark.parametrize("filename,expected_slot", SLOT_FILES.items())
    def test_ghost_cards_have_print_max_100(self, filename, expected_slot):
        with open(CARDS_DIR / filename) as f:
            cards = json.load(f)
        for card in cards:
            if card["rarity"] == "ghost":
                assert card.get("print_max") == 100, f"{card['name']} should have print_max=100"

    def test_unique_card_names_across_all_files(self):
        all_names = []
        for filename in SLOT_FILES:
            with open(CARDS_DIR / filename) as f:
                cards = json.load(f)
            all_names.extend(c["name"] for c in cards)
        assert len(all_names) == len(set(all_names)), "Duplicate card names found"

    def test_total_card_count(self):
        """Should have at least 30 cards across all files."""
        total = 0
        for filename in SLOT_FILES:
            with open(CARDS_DIR / filename) as f:
                cards = json.load(f)
            total += len(cards)
        assert total >= 30, f"Only {total} cards total, need at least 30"

    def test_rarity_distribution(self):
        """Check approximate rarity distribution."""
        counts: dict[str, int] = {r: 0 for r in VALID_RARITIES}
        total = 0
        for filename in SLOT_FILES:
            with open(CARDS_DIR / filename) as f:
                cards = json.load(f)
            for card in cards:
                counts[card["rarity"]] += 1
                total += 1

        # Common should be the most frequent
        assert counts["common"] >= counts["ghost"]
        assert total >= 30


class TestEnvironmentData:
    def test_environments_json_valid(self):
        path = DATA_DIR / "environments.json"
        assert path.exists()
        with open(path) as f:
            envs = json.load(f)
        assert isinstance(envs, list)
        assert len(envs) == 6

    def test_all_environments_have_required_fields(self):
        with open(DATA_DIR / "environments.json") as f:
            envs = json.load(f)
        for env in envs:
            assert "name" in env
            assert "display_name" in env
            assert "description" in env
            assert "stat_weights" in env
            assert isinstance(env["stat_weights"], dict)

    def test_environment_names(self):
        with open(DATA_DIR / "environments.json") as f:
            envs = json.load(f)
        names = {e["name"] for e in envs}
        expected = {
            "wet_track",
            "night_race",
            "mountain_pass",
            "drag_strip",
            "city_circuit",
            "off_road",
        }
        assert names == expected


class TestLootTables:
    def test_loot_tables_valid(self):
        path = DATA_DIR / "loot_tables.json"
        assert path.exists()
        with open(path) as f:
            tables = json.load(f)
        assert "junkyard_pack" in tables
        assert "performance_pack" in tables
        assert "legend_crate" in tables

    def test_loot_table_weights_sum_to_100(self):
        with open(DATA_DIR / "loot_tables.json") as f:
            tables = json.load(f)
        for pack_name, pack_data in tables.items():
            total = sum(pack_data["weights"].values())
            assert abs(total - 100) < 0.1, f"{pack_name} weights sum to {total}, not 100"

    def test_legend_crate_no_common_uncommon(self):
        with open(DATA_DIR / "loot_tables.json") as f:
            tables = json.load(f)
        legend = tables["legend_crate"]["weights"]
        assert legend["common"] == 0
        assert legend["uncommon"] == 0
