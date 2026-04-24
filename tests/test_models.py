"""Tests for db/models.py — enum and model validation."""

from __future__ import annotations

from db.models import CardSlot, HullClass, Rarity


class TestEnums:
    def test_hull_classes(self):
        assert HullClass.HAULER.value == "hauler"
        assert HullClass.SKIRMISHER.value == "skirmisher"
        assert HullClass.SCOUT.value == "scout"
        assert len(HullClass) == 3

    def test_card_slots(self):
        expected = {"reactor", "drive", "thrusters", "stabilizers", "hull", "overdrive", "retros"}
        actual = {s.value for s in CardSlot}
        assert actual == expected
        assert len(CardSlot) == 7

    def test_rarity_tiers(self):
        expected = {"common", "uncommon", "rare", "epic", "legendary", "ghost"}
        actual = {r.value for r in Rarity}
        assert actual == expected
        assert len(Rarity) == 6

    def test_rarity_ordering(self):
        """Rarity tiers should be defined in order from lowest to highest."""
        ordered = list(Rarity)
        assert ordered[0] == Rarity.COMMON
        assert ordered[-1] == Rarity.GHOST
