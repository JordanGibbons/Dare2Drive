"""Test /notifications command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from db.models import HullClass, User
from tests.conftest import SessionWrapper


@pytest.mark.asyncio
async def test_notifications_set_updates_prefs(db_session, monkeypatch):
    """Test that /notifications command updates user notification preferences."""
    # Create a User with default notification_prefs
    user = User(
        discord_id="123456789",
        username="testuser",
        hull_class=HullClass.HAULER,
        notification_prefs={
            "timer_completion": "dm",
            "accrual_threshold": "dm",
            "_version": 1,
        },
    )
    db_session.add(user)
    await db_session.flush()

    # Mock the async_session in fleet module to use our test session
    from bot.cogs import fleet as fleet_mod

    monkeypatch.setattr(fleet_mod, "async_session", lambda: SessionWrapper(db_session))

    # Create a mock interaction
    interaction = AsyncMock()
    interaction.user.id = int(user.discord_id)
    interaction.response.send_message = AsyncMock()

    # Create the cog and call the notifications command
    from bot.cogs.fleet import FleetCog

    bot = MagicMock()
    cog = FleetCog(bot)

    # Call the notifications command with category and value
    await cog.notifications.callback(cog, interaction, category="timer_completion", value="off")

    # Verify the response was sent
    interaction.response.send_message.assert_called_once()
    call_args = interaction.response.send_message.call_args
    assert "`timer_completion` set to **off**." in call_args[0][0]

    # Refresh the user from the database to verify the change was persisted
    await db_session.refresh(user)
    assert user.notification_prefs["timer_completion"] == "off"
    assert user.notification_prefs["_version"] == 1
