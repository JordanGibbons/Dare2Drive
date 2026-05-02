"""Tests for engine/card_mint.py."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from engine.card_mint import (
    STAT_VARIANCE_RANGE,
    apply_stat_modifiers,
    degrade_stat_modifiers,
    delete_tutorial_cards,
    mint_tutorial_card,
    roll_stat_modifiers,
)

# ---------------------------------------------------------------------------
# roll_stat_modifiers
# ---------------------------------------------------------------------------


class TestRollStatModifiers:
    def test_returns_modifiers_for_each_stat(self):
        stats = {"primary": {"power": 60, "torque": 50}, "secondary": {"durability": 70}}
        mods = roll_stat_modifiers(stats)
        assert set(mods["primary"]) == {"power", "torque"}
        assert set(mods["secondary"]) == {"durability"}

    def test_modifiers_within_variance_range(self):
        stats = {"primary": {"power": 60, "torque": 50, "acceleration": 55}}
        for _ in range(50):
            mods = roll_stat_modifiers(stats)
            for val in mods["primary"].values():
                assert -STAT_VARIANCE_RANGE <= val <= STAT_VARIANCE_RANGE

    def test_non_numeric_stats_skipped(self):
        stats = {"primary": {"power": 60, "label": "fast"}, "secondary": {}}
        mods = roll_stat_modifiers(stats)
        assert "label" not in mods.get("primary", {})

    def test_empty_section_omitted(self):
        stats = {"primary": {"power": 60}, "secondary": {}}
        mods = roll_stat_modifiers(stats)
        assert "secondary" not in mods

    def test_entirely_empty_stats(self):
        mods = roll_stat_modifiers({})
        assert mods == {}

    def test_modifiers_are_rounded_to_4_places(self):
        stats = {"primary": {"power": 60}}
        for _ in range(20):
            mods = roll_stat_modifiers(stats)
            val = mods["primary"]["power"]
            assert val == round(val, 4)


# ---------------------------------------------------------------------------
# apply_stat_modifiers
# ---------------------------------------------------------------------------


class TestApplyStatModifiers:
    def test_applies_positive_modifier(self):
        base = {"primary": {"power": 100}, "secondary": {}}
        mods = {"primary": {"power": 0.05}}
        result = apply_stat_modifiers(base, mods)
        assert result["primary"]["power"] == pytest.approx(105.0, rel=1e-3)

    def test_applies_negative_modifier(self):
        base = {"primary": {"power": 100}, "secondary": {}}
        mods = {"primary": {"power": -0.05}}
        result = apply_stat_modifiers(base, mods)
        assert result["primary"]["power"] == pytest.approx(95.0, rel=1e-3)

    def test_stat_without_modifier_unchanged(self):
        base = {"primary": {"power": 80, "torque": 60}, "secondary": {}}
        mods = {"primary": {"power": 0.1}}
        result = apply_stat_modifiers(base, mods)
        assert result["primary"]["torque"] == 60

    def test_non_numeric_stat_passed_through(self):
        base = {"primary": {"label": "fast"}, "secondary": {}}
        mods = {}
        result = apply_stat_modifiers(base, mods)
        assert result["primary"]["label"] == "fast"

    def test_empty_modifiers_returns_base_values(self):
        base = {"primary": {"power": 75}, "secondary": {"durability": 55}}
        result = apply_stat_modifiers(base, {})
        assert result["primary"]["power"] == 75
        assert result["secondary"]["durability"] == 55

    def test_both_sections_processed(self):
        base = {"primary": {"power": 50}, "secondary": {"durability": 60}}
        mods = {"primary": {"power": 0.1}, "secondary": {"durability": -0.1}}
        result = apply_stat_modifiers(base, mods)
        assert result["primary"]["power"] == pytest.approx(55.0, rel=1e-3)
        assert result["secondary"]["durability"] == pytest.approx(54.0, rel=1e-3)


# ---------------------------------------------------------------------------
# degrade_stat_modifiers
# ---------------------------------------------------------------------------


class TestDegradeStatModifiers:
    def test_reduces_each_modifier_by_severity(self):
        mods = {"primary": {"power": 0.05, "torque": 0.02}}
        result = degrade_stat_modifiers(mods, severity=0.005)
        assert result["primary"]["power"] == pytest.approx(0.045, rel=1e-3)
        assert result["primary"]["torque"] == pytest.approx(0.015, rel=1e-3)

    def test_can_go_negative(self):
        mods = {"primary": {"power": 0.001}}
        result = degrade_stat_modifiers(mods, severity=0.005)
        assert result["primary"]["power"] < 0

    def test_does_not_mutate_input(self):
        mods = {"primary": {"power": 0.05}}
        original = mods["primary"]["power"]
        degrade_stat_modifiers(mods)
        assert mods["primary"]["power"] == original

    def test_default_severity(self):
        mods = {"primary": {"power": 0.05}}
        result = degrade_stat_modifiers(mods)
        assert result["primary"]["power"] == pytest.approx(0.045, rel=1e-3)

    def test_empty_modifiers(self):
        assert degrade_stat_modifiers({}) == {}


# ---------------------------------------------------------------------------
# delete_tutorial_cards — promotion + cleanup
# ---------------------------------------------------------------------------


async def _seed_card(session, *, slot, name="X", rarity="common"):
    from db.models import Card, CardSlot, Rarity

    card = Card(
        id=uuid.uuid4(),
        name=name,
        slot=CardSlot(slot),
        rarity=Rarity(rarity),
        stats={"primary": {"power": 50}},
        total_minted=0,
    )
    session.add(card)
    await session.flush()
    return card


@pytest.mark.asyncio
async def test_delete_tutorial_cards_promotes_cards_locked_in_active_titles(
    db_session, sample_user
):
    """A tutorial card referenced in an active ship title's snapshot must be
    promoted (real serial + variance) instead of deleted — otherwise the title
    becomes a zombie reference and the hangar shows Empty for every slot."""
    from db.models import (
        Build,
        CardSlot,
        HullClass,
        RaceFormat,
        ShipRelease,
        ShipStatus,
        ShipTitle,
    )

    card = await _seed_card(db_session, slot="reactor", name="Atomic Heart")
    uc = await mint_tutorial_card(db_session, sample_user.discord_id, card)
    assert uc.serial_number == 0  # confirm fixture preconditions

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Test",
        slots={s.value: (str(uc.id) if s == CardSlot.REACTOR else None) for s in CardSlot},
        is_active=True,
        hull_class=HullClass.SKIRMISHER,
        core_locked=True,
    )
    db_session.add(build)

    release = ShipRelease(
        id=uuid.uuid4(),
        name="Test Release",
        started_at=datetime.now(timezone.utc),
        serial_counter=1,
    )
    db_session.add(release)
    await db_session.flush()

    title = ShipTitle(
        id=uuid.uuid4(),
        release_id=release.id,
        release_serial=1,
        owner_id=sample_user.discord_id,
        build_id=build.id,
        hull_class=HullClass.SKIRMISHER,
        race_format=RaceFormat.SPRINT,
        status=ShipStatus.ACTIVE,
        auto_name="Test Ship",
        build_snapshot={
            "reactor": {
                "card_id": str(card.id),
                "user_card_id": str(uc.id),
                "serial": 0,
                "name": card.name,
                "rarity": "common",
            },
        },
    )
    db_session.add(title)
    build.ship_title_id = title.id
    await db_session.flush()

    deleted = await delete_tutorial_cards(db_session, sample_user.discord_id)
    await db_session.flush()

    # The card must NOT have been deleted — it was locked into an active title.
    assert deleted == 0
    refreshed_uc = await db_session.get(type(uc), uc.id)
    assert refreshed_uc is not None
    assert refreshed_uc.serial_number > 0, "promoted card must have a real serial"
    assert refreshed_uc.stat_modifiers, "promoted card must have rolled variance"

    # Snapshot must reflect the new serial — otherwise the hangar shows the old #0.
    refreshed_title = await db_session.get(ShipTitle, title.id)
    assert refreshed_title.build_snapshot["reactor"]["serial"] == refreshed_uc.serial_number

    # Build slot still points at the same UserCard id.
    refreshed_build = await db_session.get(Build, build.id)
    assert refreshed_build.slots["reactor"] == str(uc.id)


@pytest.mark.asyncio
async def test_delete_tutorial_cards_still_deletes_unlocked_tutorial_cards(db_session, sample_user):
    """Tutorial cards NOT locked in any title must be deleted as before, and
    cleared from the active build's slots."""
    from db.models import Build, CardSlot, HullClass, UserCard

    card = await _seed_card(db_session, slot="drive", name="Free Drive")
    uc = await mint_tutorial_card(db_session, sample_user.discord_id, card)

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Test",
        slots={s.value: (str(uc.id) if s == CardSlot.DRIVE else None) for s in CardSlot},
        is_active=True,
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add(build)
    await db_session.flush()

    deleted = await delete_tutorial_cards(db_session, sample_user.discord_id)
    await db_session.flush()

    assert deleted == 1
    assert await db_session.get(UserCard, uc.id) is None

    refreshed_build = await db_session.get(Build, build.id)
    assert refreshed_build.slots["drive"] is None


@pytest.mark.asyncio
async def test_delete_tutorial_cards_ignores_scrapped_titles(db_session, sample_user):
    """A scrapped title doesn't protect its tutorial-card refs — the card should
    be deleted as normal, since the title is no longer race-eligible."""
    from db.models import (
        Build,
        CardSlot,
        HullClass,
        RaceFormat,
        ShipRelease,
        ShipStatus,
        ShipTitle,
        UserCard,
    )

    card = await _seed_card(db_session, slot="hull", name="Scrapped Hull")
    uc = await mint_tutorial_card(db_session, sample_user.discord_id, card)

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Test",
        slots={s.value: None for s in CardSlot},
        is_active=True,
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add(build)

    release = ShipRelease(
        id=uuid.uuid4(),
        name="R",
        started_at=datetime.now(timezone.utc),
        serial_counter=1,
    )
    db_session.add(release)
    await db_session.flush()

    title = ShipTitle(
        id=uuid.uuid4(),
        release_id=release.id,
        release_serial=1,
        owner_id=sample_user.discord_id,
        hull_class=HullClass.SKIRMISHER,
        race_format=RaceFormat.SPRINT,
        status=ShipStatus.SCRAPPED,
        auto_name="Old",
        build_snapshot={
            "hull": {
                "card_id": str(card.id),
                "user_card_id": str(uc.id),
                "serial": 0,
                "name": card.name,
                "rarity": "common",
            },
        },
    )
    db_session.add(title)
    await db_session.flush()

    deleted = await delete_tutorial_cards(db_session, sample_user.discord_id)
    await db_session.flush()
    assert deleted == 1
    assert await db_session.get(UserCard, uc.id) is None
