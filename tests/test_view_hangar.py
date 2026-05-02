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

    from bot.views.hangar_view import HangarSlotSelect

    embed, view = await render_hangar_view(db_session, build, sample_user)
    assert "Flagstaff" in embed.description or "Flagstaff" in embed.title
    # Skirmisher = 2 crew slots (PILOT, GUNNER) → 2 HangarSlotSelect dynamic items
    selects = [c for c in view.children if isinstance(c, HangarSlotSelect)]
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

    from bot.views.hangar_view import HangarSlotSelect

    embed, view = await render_hangar_view(db_session, build, sample_user)
    selects = [c for c in view.children if isinstance(c, HangarSlotSelect)]
    assert selects, "expected disabled slot selects to be present"
    # Each DynamicItem wraps a discord.ui.Select; the disabled flag lives on
    # the wrapped item.
    assert all(s.item.disabled for s in selects)


@pytest.mark.asyncio
async def test_hangar_assign_inserts_build_crew_assignment(db_session, sample_user, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from bot.views import hangar_view as hv
    from db.models import (
        Build,
        CrewArchetype,
        CrewAssignment,
        CrewMember,
        HullClass,
        Rarity,
    )
    from tests.conftest import SessionWrapper

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

    monkeypatch.setattr(hv, "async_session", lambda: SessionWrapper(db_session))

    interaction = MagicMock()
    interaction.user.id = sample_user.discord_id
    interaction.data = {
        "custom_id": hv.make_select_custom_id(build.id, "PILOT"),
        "values": [str(crew.id)],
    }
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_message = AsyncMock()

    select_item = hv.HangarSlotSelect(
        build.id,
        CrewArchetype.PILOT,
        options=[discord.SelectOption(label="(stub)", value="stub")],
    )
    await select_item.callback(interaction)

    from sqlalchemy import select

    rows = (
        (
            await db_session.execute(
                select(CrewAssignment)
                .where(CrewAssignment.build_id == build.id)
                .where(CrewAssignment.archetype == CrewArchetype.PILOT)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].crew_id == crew.id


@pytest.mark.asyncio
async def test_hangar_unassign_removes_build_crew_assignment(db_session, sample_user, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy import select

    from bot.views import hangar_view as hv
    from db.models import (
        Build,
        CrewArchetype,
        CrewAssignment,
        CrewMember,
        HullClass,
        Rarity,
    )
    from tests.conftest import SessionWrapper

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

    monkeypatch.setattr(hv, "async_session", lambda: SessionWrapper(db_session))

    interaction = MagicMock()
    interaction.user.id = sample_user.discord_id
    interaction.data = {
        "custom_id": hv.make_select_custom_id(build.id, "PILOT"),
        "values": [hv.UNASSIGN_VALUE],
    }
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_message = AsyncMock()

    select_item = hv.HangarSlotSelect(
        build.id,
        CrewArchetype.PILOT,
        options=[discord.SelectOption(label="(stub)", value="stub")],
    )
    await select_item.callback(interaction)

    rows = (
        (
            await db_session.execute(
                select(CrewAssignment).where(CrewAssignment.build_id == build.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


def test_setup_hook_registers_hangar_dynamic_item():
    """Persistent click routing contract: HangarSlotSelect is registered as a
    DynamicItem at bot startup so /hangar select interactions survive restarts."""
    import inspect

    from bot import main as main_mod

    source = inspect.getsource(main_mod)
    assert "HangarSlotSelect" in source, "bot/main.py must reference HangarSlotSelect"
    assert "add_dynamic_items" in source, (
        "bot/main.py must call add_dynamic_items() — add_view alone won't route "
        "parameterized custom_ids on persistent components"
    )


def test_setup_hook_always_syncs_globally():
    """Guild-only sync hides slash commands from DMs. Global sync must be unconditional."""
    import ast
    import inspect
    import textwrap

    from bot import main as main_mod

    source = textwrap.dedent(inspect.getsource(main_mod.Dare2DriveBot.setup_hook))
    tree = ast.parse(source)

    def is_global_tree_sync(stmt: ast.AST) -> bool:
        # Top-level `await self.tree.sync()` parses as Expr(Await(Call(...))).
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Await)):
            return False
        call = stmt.value.value
        if not isinstance(call, ast.Call):
            return False
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "sync"
            and isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr == "tree"
        ):
            return False
        return not any(kw.arg == "guild" for kw in call.keywords)

    # Find the function body and inspect its top-level statements only — a global
    # tree.sync() inside an `if`/`else` branch is the bug we're guarding against.
    func_def = tree.body[0]
    assert isinstance(func_def, ast.AsyncFunctionDef)
    top_level_global_syncs = [n for n in func_def.body if is_global_tree_sync(n)]
    assert top_level_global_syncs, (
        "setup_hook must call `await self.tree.sync()` at the top level "
        "(not gated behind DISCORD_GUILD_ID) so commands appear in DMs"
    )
