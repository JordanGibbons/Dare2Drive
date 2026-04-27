"""/expedition status cog tests — list mode + per-expedition timeline mode."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_interaction(user_id):
    inter = MagicMock()
    inter.user.id = int(user_id) if str(user_id).isdigit() else user_id
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.is_done = MagicMock(return_value=False)
    return inter


@pytest.mark.asyncio
async def test_status_no_arg_shows_no_active_message(db_session, sample_user, monkeypatch):
    from bot.cogs import expeditions as exp_mod
    from tests.conftest import SessionWrapper

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))

    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(sample_user.discord_id)
    await cog.expedition_status.callback(cog, inter, expedition=None)
    msg = inter.response.send_message.call_args.args[0]
    assert "no active" in msg.lower() or "none" in msg.lower()


@pytest.mark.asyncio
async def test_status_no_arg_lists_active(db_session, sample_expedition_with_pilot, monkeypatch):
    from bot.cogs import expeditions as exp_mod
    from tests.conftest import SessionWrapper

    expedition, _ = sample_expedition_with_pilot

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(expedition.user_id)
    await cog.expedition_status.callback(cog, inter, expedition=None)
    msg = inter.response.send_message.call_args.args[0]
    assert "active" in msg.lower()
    assert expedition.template_id in msg or "marquee" in msg.lower() or "outer" in msg.lower()


@pytest.mark.asyncio
async def test_status_per_expedition_renders_timeline(
    db_session, sample_expedition_with_pilot, monkeypatch
):
    from bot.cogs import expeditions as exp_mod
    from tests.conftest import SessionWrapper

    expedition, _ = sample_expedition_with_pilot
    expedition.scene_log = [
        {
            "scene_id": "pirate_skiff",
            "status": "resolved",
            "fired_at": "2026-04-26T12:00:00Z",
            "resolved_at": "2026-04-26T12:18:00Z",
            "choice_id": "outrun",
            "narrative": "Mira pins the throttle.",
            "auto_resolved": False,
            "roll": {"success": True},
        },
        {
            "scene_id": "scope_ghost",
            "status": "pending",
            "fired_at": "2026-04-26T14:00:00Z",
            "visible_choice_ids": ["pursue", "log_only"],
            "auto_resolve_job_id": str(uuid.uuid4()),
        },
    ]
    await db_session.flush()

    monkeypatch.setattr(exp_mod, "async_session", lambda: SessionWrapper(db_session))
    cog = exp_mod.ExpeditionsCog(MagicMock())
    inter = _make_interaction(expedition.user_id)
    await cog.expedition_status.callback(cog, inter, expedition=str(expedition.id))
    msg = inter.response.send_message.call_args.args[0]
    assert "pirate_skiff" in msg or "outrun" in msg.lower()
    assert "scope_ghost" in msg or "pending" in msg.lower()
