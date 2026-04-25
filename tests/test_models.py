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


def test_crew_archetype_enum_values():
    from db.models import CrewArchetype

    assert {a.value for a in CrewArchetype} == {"pilot", "engineer", "gunner", "navigator", "medic"}


def test_crew_member_has_required_fields():
    from db.models import CrewMember

    fields = {c.name for c in CrewMember.__table__.columns}
    assert fields >= {
        "id",
        "user_id",
        "first_name",
        "last_name",
        "callsign",
        "archetype",
        "rarity",
        "level",
        "xp",
        "portrait_key",
        "acquired_at",
        "retired_at",
    }


def test_crew_assignment_has_required_fields():
    from db.models import CrewAssignment

    fields = {c.name for c in CrewAssignment.__table__.columns}
    assert fields >= {"id", "crew_id", "build_id", "archetype", "assigned_at"}


def test_crew_daily_lead_has_required_fields():
    from db.models import CrewDailyLead

    fields = {c.name for c in CrewDailyLead.__table__.columns}
    assert fields >= {
        "user_id",
        "rolled_for_date",
        "archetype",
        "rarity",
        "first_name",
        "last_name",
        "callsign",
        "claimed_at",
        "created_at",
    }
