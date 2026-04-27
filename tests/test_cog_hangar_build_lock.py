"""Hangar cog refuses build-mutation commands while build is ON_EXPEDITION."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest


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
