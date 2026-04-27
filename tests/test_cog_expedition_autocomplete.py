"""Autocomplete handlers — players should never type template/build/crew IDs."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


def _make_interaction(user_id):
    inter = MagicMock()
    inter.user.id = int(user_id) if str(user_id).isdigit() else user_id
    return inter


@pytest.mark.asyncio
async def test_template_autocomplete_lists_committed_templates():
    from bot.cogs.expeditions import _template_autocomplete

    inter = _make_interaction("123")
    out = await _template_autocomplete(inter, "")
    template_ids = {c.value for c in out}
    # v1 ships these two; CI gate enforces ≥2 templates
    assert "marquee_run" in template_ids
    assert "outer_marker_patrol" in template_ids
    # Display name is human-readable, not the raw id
    for c in out:
        assert "_" not in c.name.split(" (")[0], f"display name still has underscores: {c.name}"


@pytest.mark.asyncio
async def test_template_autocomplete_filters_by_current():
    from bot.cogs.expeditions import _template_autocomplete

    inter = _make_interaction("123")
    out = await _template_autocomplete(inter, "patrol")
    assert {c.value for c in out} == {"outer_marker_patrol"}


@pytest.mark.asyncio
async def test_build_autocomplete_lists_idle_builds_only(db_session, sample_user, monkeypatch):
    from bot.cogs import expeditions as exp_mod
    from db.models import Build, BuildActivity, HullClass
    from tests.conftest import SessionWrapper

    idle = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.IDLE,
    )
    busy = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Wanderer",
        hull_class=HullClass.HAULER,
        current_activity=BuildActivity.ON_EXPEDITION,
    )
    db_session.add_all([idle, busy])
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    inter = _make_interaction(sample_user.discord_id)
    out = await exp_mod._build_autocomplete(inter, "")

    values = {c.value for c in out}
    assert str(idle.id) in values
    assert str(busy.id) not in values  # ON_EXPEDITION builds shouldn't appear


@pytest.mark.asyncio
async def test_pilot_autocomplete_filters_by_archetype_and_idle(
    db_session, sample_user, monkeypatch
):
    from bot.cogs import expeditions as exp_mod
    from db.models import CrewActivity, CrewArchetype, CrewMember, Rarity
    from tests.conftest import SessionWrapper

    pilot_idle = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
        current_activity=CrewActivity.IDLE,
    )
    pilot_busy = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Other",
        last_name="Pilot",
        callsign="Vex",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
        level=1,
        current_activity=CrewActivity.ON_EXPEDITION,
    )
    pilot_injured = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Hurt",
        last_name="Pilot",
        callsign="Bandage",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
        level=1,
        current_activity=CrewActivity.IDLE,
        injured_until=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    gunner_idle = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Jax",
        last_name="Krell",
        callsign="Blackjack",
        archetype=CrewArchetype.GUNNER,
        rarity=Rarity.RARE,
        level=3,
        current_activity=CrewActivity.IDLE,
    )
    db_session.add_all([pilot_idle, pilot_busy, pilot_injured, gunner_idle])
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    inter = _make_interaction(sample_user.discord_id)
    out = await exp_mod._pilot_autocomplete(inter, "")

    values = {c.value for c in out}
    assert 'Mira "Sixgun" Voss' in values
    assert 'Other "Vex" Pilot' not in values  # ON_EXPEDITION
    assert 'Hurt "Bandage" Pilot' not in values  # injured
    assert 'Jax "Blackjack" Krell' not in values  # wrong archetype


@pytest.mark.asyncio
async def test_active_expedition_autocomplete_lists_only_active(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    from bot.cogs import expeditions as exp_mod
    from db.models import ExpeditionState
    from tests.conftest import SessionWrapper

    expedition, _ = sample_expedition_with_pilot

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    inter = _make_interaction(expedition.user_id)
    out = await exp_mod._active_expedition_autocomplete(inter, "")
    values = {c.value for c in out}
    assert str(expedition.id) in values

    # Now mark it COMPLETED — it should drop out
    expedition.state = ExpeditionState.COMPLETED
    await db_session.flush()
    out_after = await exp_mod._active_expedition_autocomplete(inter, "")
    assert str(expedition.id) not in {c.value for c in out_after}


def test_expedition_start_has_autocompletes_wired():
    """Regression test: every player-facing string parameter must have an autocomplete."""
    from bot.cogs.expeditions import ExpeditionsCog

    cog = ExpeditionsCog(MagicMock())
    autocompletes = cog.expedition_start._params  # discord.py stores per-param metadata
    for param_name in ("template", "build", "pilot", "gunner", "engineer", "navigator"):
        param = autocompletes.get(param_name)
        assert param is not None, f"missing param descriptor for {param_name}"
        assert param.autocomplete is not None, f"{param_name} has no autocomplete handler"
