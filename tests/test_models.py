"""Tests for db/models.py — enum and model validation."""

from __future__ import annotations

from db.models import BodyType, CardSlot, Rarity


class TestEnums:
    def test_body_types(self):
        assert BodyType.MUSCLE.value == "muscle"
        assert BodyType.SPORT.value == "sport"
        assert BodyType.COMPACT.value == "compact"
        assert len(BodyType) == 3

    def test_card_slots(self):
        expected = {"engine", "transmission", "tires", "suspension", "chassis", "turbo", "brakes"}
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
