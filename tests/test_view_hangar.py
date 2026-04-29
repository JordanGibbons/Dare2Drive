"""HangarView — custom_id encoding/decoding tests."""

from __future__ import annotations

import uuid

import discord
import pytest


def test_make_select_custom_id_format():
    from bot.views.hangar_view import make_select_custom_id

    build_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    out = make_select_custom_id(build_id, "PILOT")
    assert out == "hangar:slot:12345678-1234-5678-1234-567812345678:PILOT"


def test_parse_select_custom_id_round_trip():
    from bot.views.hangar_view import make_select_custom_id, parse_select_custom_id

    build_id = uuid.uuid4()
    cid = make_select_custom_id(build_id, "GUNNER")
    parsed = parse_select_custom_id(cid)
    assert parsed == (build_id, "GUNNER")


def test_parse_select_custom_id_rejects_unknown_prefix():
    from bot.views.hangar_view import parse_select_custom_id

    assert parse_select_custom_id("expedition:button:foo:bar") is None
    assert parse_select_custom_id("totally bogus") is None


@pytest.mark.asyncio
async def test_render_hangar_view_returns_embed_and_view(db_session, sample_user):
    from bot.views.hangar_view import render_hangar_view
    from db.models import Build, HullClass

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add(build)
    await db_session.flush()

    embed, view = await render_hangar_view(db_session, build, sample_user)
    assert "Flagstaff" in embed.description or "Flagstaff" in embed.title
    # Skirmisher = 2 crew slots (PILOT, GUNNER) → 2 Select children
    selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
    assert len(selects) == 2


@pytest.mark.asyncio
async def test_render_hangar_view_filled_slot_shows_crew_name(db_session, sample_user):
    from bot.views.hangar_view import render_hangar_view
    from db.models import (
        Build,
        CrewArchetype,
        CrewAssignment,
        CrewMember,
        HullClass,
        Rarity,
    )

    crew = CrewMember(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        first_name="Mira",
        last_name="Voss",
        callsign="Sixgun",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.RARE,
        level=4,
    )
    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
    )
    db_session.add_all([crew, build])
    await db_session.flush()
    db_session.add(
        CrewAssignment(build_id=build.id, crew_id=crew.id, archetype=CrewArchetype.PILOT)
    )
    await db_session.flush()

    embed, view = await render_hangar_view(db_session, build, sample_user)
    description = embed.description or ""
    assert "Mira" in description and "Sixgun" in description


@pytest.mark.asyncio
async def test_render_hangar_view_disables_selects_when_on_expedition(db_session, sample_user):
    from bot.views.hangar_view import render_hangar_view
    from db.models import Build, BuildActivity, HullClass

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Flagstaff",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.ON_EXPEDITION,
    )
    db_session.add(build)
    await db_session.flush()

    embed, view = await render_hangar_view(db_session, build, sample_user)
    selects = [c for c in view.children if isinstance(c, discord.ui.Select)]
    assert all(s.disabled for s in selects)
