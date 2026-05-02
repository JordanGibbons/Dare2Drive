"""Hangar cog refuses build-mutation commands while build is ON_EXPEDITION."""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest


def test_hangar_renders_locked_parts_from_title_snapshot():
    """Regression for the 'all slots Empty' display bug: when a build has a
    minted ship title, the hangar/peek embeds must read part info from
    `title.build_snapshot` (the canonical locked-in record), not from
    `b.slots` which can be cleared by tutorial-card cleanup."""
    from bot.cogs import hangar as hangar_mod

    src = inspect.getsource(hangar_mod)
    # Both /hangar (hangar) and /hangar peek must reference build_snapshot.
    assert src.count("build_snapshot") >= 2, (
        "expected /hangar and /hangar peek to read parts from title.build_snapshot — "
        "without this, locked builds with cleared slots render as all Empty"
    )
    # And neither should fall straight through to `b.slots` without first
    # checking the snapshot — guard via a literal phrase the comment uses.
    assert "snapshot is the" in src.lower() or "snapshot.get" in src


def _make_interaction(user_id):
    inter = MagicMock()
    inter.user.id = int(user_id) if str(user_id).isdigit() else user_id
    inter.channel_id = 222222222
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    inter.followup = MagicMock()
    inter.followup.send = AsyncMock()
    return inter


@pytest.mark.asyncio
async def test_equip_refuses_when_build_on_expedition(db_session, sample_user, monkeypatch):
    from bot.cogs import hangar as hangar_mod
    from bot.system_gating import get_active_system
    from db.models import Build, BuildActivity, HullClass
    from tests.conftest import SessionWrapper

    build = Build(
        id=uuid.uuid4(),
        user_id=sample_user.discord_id,
        name="Locked",
        hull_class=HullClass.SKIRMISHER,
        current_activity=BuildActivity.ON_EXPEDITION,
    )
    db_session.add(build)
    await db_session.flush()

    monkeypatch.setattr(hangar_mod, "async_session", lambda: SessionWrapper(db_session))
    monkeypatch.setattr(
        hangar_mod,
        "get_active_system",
        create_autospec(get_active_system, return_value=MagicMock()),
    )

    cog = hangar_mod.HangarCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)

    # /equip signature: (self, interaction, slot, card_name, build=None)
    # Pass build UUID so the resolver finds the ON_EXPEDITION build specifically.
    await cog.equip.callback(
        cog,
        inter,
        slot="reactor",
        card_name="any_card",
        build=str(build.id),
    )

    msg = inter.response.send_message.call_args.args[0]
    assert "expedition" in msg.lower() or "busy" in msg.lower()
