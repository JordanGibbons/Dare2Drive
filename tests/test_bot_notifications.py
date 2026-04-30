"""Tests for bot.notifications — Redis-stream consumer + rate-limit + batching."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from db.models import HullClass, User


class _SessionContext:
    """Thin async context manager that wraps the test's db_session.

    The consumer calls ``async with async_session() as session`` to look up
    User rows.  Because the test's ``db_session`` fixture uses a savepoint on
    a single connection, rows flushed inside the test are NOT visible to a
    fresh session opened against a different connection.

    We monkeypatch ``bot.notifications.async_session`` to return this wrapper
    so the consumer shares the test's connection and can see the unflushed user.
    """

    def __init__(self, session):
        self._s = session

    async def __aenter__(self):
        return self._s

    async def __aexit__(self, *a):
        return None  # don't close — the fixture handles teardown


@pytest.mark.asyncio
async def test_consumer_sends_dm_for_in_band_message(db_session, redis_client, monkeypatch):
    from bot import notifications as notifs

    monkeypatch.setattr(
        "bot.notifications.async_session",
        lambda: _SessionContext(db_session),
    )

    user = User(
        discord_id="600101",
        username="cn_a",
        hull_class=HullClass.HAULER,
        notification_prefs={"timer_completion": "dm", "accrual_threshold": "dm", "_version": 1},
    )
    db_session.add(user)
    await db_session.flush()

    sent: list[dict[str, Any]] = []

    class FakeUser:
        async def send(self, content: str | None = None, embed=None):
            sent.append({"content": content, "embed": embed})

    class FakeBot:
        async def fetch_user(self, _id: int):
            return FakeUser()

    await redis_client.xadd(
        "d2d:notifications:test",
        {
            "user_id": "600101",
            "category": "timer_completion",
            "title": "T",
            "body": "B",
            "correlation_id": "c",
            "dedupe_key": "k",
            "created_at": "now",
        },
    )

    consumer = notifs.NotificationConsumer(
        bot=FakeBot(),
        redis=redis_client,
        stream_key="d2d:notifications:test",
        consumer_group="d2d-bot-test",
        consumer_id="bot-test-1",
        batch_window_seconds=0,  # immediate flush.
        start_id="0",  # test XADDs before ensure_group; deliver from start.
    )
    await consumer.ensure_group()
    await consumer.process_once(block_ms=200)
    await asyncio.sleep(0.05)
    await consumer.flush_pending()

    assert len(sent) == 1
    assert "T" in (sent[0]["content"] or "") or sent[0]["embed"] is not None


@pytest.mark.asyncio
async def test_consumer_skips_opted_out_user(db_session, redis_client, monkeypatch):
    from bot import notifications as notifs

    monkeypatch.setattr(
        "bot.notifications.async_session",
        lambda: _SessionContext(db_session),
    )

    user = User(
        discord_id="600102",
        username="cn_b",
        hull_class=HullClass.HAULER,
        notification_prefs={"timer_completion": "off", "accrual_threshold": "dm", "_version": 1},
    )
    db_session.add(user)
    await db_session.flush()

    sent: list[Any] = []

    class FakeBot:
        async def fetch_user(self, _id: int):
            class FU:
                async def send(self, *a, **kw):
                    sent.append((a, kw))

            return FU()

    await redis_client.xadd(
        "d2d:notifications:test_optout",
        {
            "user_id": "600102",
            "category": "timer_completion",
            "title": "T",
            "body": "B",
            "correlation_id": "c",
            "dedupe_key": "k",
            "created_at": "now",
        },
    )

    consumer = notifs.NotificationConsumer(
        bot=FakeBot(),
        redis=redis_client,
        stream_key="d2d:notifications:test_optout",
        consumer_group="g",
        consumer_id="c1",
        batch_window_seconds=0,
        start_id="0",
    )
    await consumer.ensure_group()
    await consumer.process_once(block_ms=200)
    await consumer.flush_pending()

    assert sent == []  # opted out — silent drop.


@pytest.mark.asyncio
async def test_consumer_rate_limit_drops_excess(db_session, redis_client, monkeypatch):
    from bot import notifications as notifs

    monkeypatch.setattr(
        "bot.notifications.async_session",
        lambda: _SessionContext(db_session),
    )

    user = User(
        discord_id="600103",
        username="cn_c",
        hull_class=HullClass.HAULER,
        notification_prefs={"timer_completion": "dm", "accrual_threshold": "dm", "_version": 1},
    )
    db_session.add(user)
    await db_session.flush()

    sent: list[str] = []

    class FakeBot:
        async def fetch_user(self, _id: int):
            class FU:
                async def send(self, content=None, embed=None):
                    sent.append(content or "")

            return FU()

    for i in range(10):
        await redis_client.xadd(
            "d2d:notifications:test_rate",
            {
                "user_id": "600103",
                "category": "timer_completion",
                "title": f"T{i}",
                "body": "B",
                "correlation_id": "c",
                "dedupe_key": f"k{i}",
                "created_at": "now",
            },
        )

    consumer = notifs.NotificationConsumer(
        bot=FakeBot(),
        redis=redis_client,
        stream_key="d2d:notifications:test_rate",
        consumer_group="g",
        consumer_id="c1",
        batch_window_seconds=0,
        rate_limit_per_hour=3,
        start_id="0",
    )
    await consumer.ensure_group()
    for _ in range(10):
        await consumer.process_once(block_ms=200)
    await consumer.flush_pending()

    assert len(sent) <= 3


@pytest.mark.asyncio
async def test_consumer_attaches_view_when_components_present(
    db_session, redis_client, monkeypatch
):
    """A notification carrying components must be sent with a discord.ui.View
    whose buttons preserve the custom_ids — this is what the persistent
    ExpeditionResponseView matches against to handle clicks."""
    import json

    import discord

    from bot import notifications as notifs

    monkeypatch.setattr(
        "bot.notifications.async_session",
        lambda: _SessionContext(db_session),
    )

    user = User(
        discord_id="600104",
        username="cn_d",
        hull_class=HullClass.HAULER,
        notification_prefs={"expedition_event": "dm", "_version": 1},
    )
    db_session.add(user)
    await db_session.flush()

    captured: list[dict] = []

    class FakeUser:
        id = 600104

        async def send(self, content=None, *, view=None, embed=None):
            captured.append({"content": content, "view": view, "embed": embed})

    class FakeBot:
        async def fetch_user(self, _id: int):
            return FakeUser()

    components = [
        {"custom_id": "expedition:abc:scene1:run", "label": "Run", "style": "primary"},
        {"custom_id": "expedition:abc:scene1:fight", "label": "Fight", "style": "danger"},
    ]
    await redis_client.xadd(
        "d2d:notifications:test_components",
        {
            "user_id": "600104",
            "category": "expedition_event",
            "title": "Pirate skiff",
            "body": "Choose:",
            "correlation_id": "c",
            "dedupe_key": "k",
            "created_at": "now",
            "components": json.dumps(components),
        },
    )

    consumer = notifs.NotificationConsumer(
        bot=FakeBot(),
        redis=redis_client,
        stream_key="d2d:notifications:test_components",
        consumer_group="g_components",
        consumer_id="c1",
        batch_window_seconds=0,
        start_id="0",
    )
    await consumer.ensure_group()
    await consumer.process_once(block_ms=200)
    await consumer.flush_pending()

    assert len(captured) == 1
    sent = captured[0]
    assert sent["view"] is not None
    buttons = [c for c in sent["view"].children if isinstance(c, discord.ui.Button)]
    assert [b.custom_id for b in buttons] == [c["custom_id"] for c in components]
    assert [b.label for b in buttons] == ["Run", "Fight"]
    # Style "danger" must round-trip — silent default would mask routing bugs.
    assert buttons[1].style == discord.ButtonStyle.danger


@pytest.mark.asyncio
async def test_consumer_does_not_batch_components_with_plain_items(
    db_session, redis_client, monkeypatch
):
    """A button-bearing item must arrive as its own DM, separate from any
    plain items batched at the same time, so buttons stay anchored to the
    narration that prompted them."""
    import json

    from bot import notifications as notifs

    monkeypatch.setattr(
        "bot.notifications.async_session",
        lambda: _SessionContext(db_session),
    )

    user = User(
        discord_id="600105",
        username="cn_e",
        hull_class=HullClass.HAULER,
        notification_prefs={
            "expedition_event": "dm",
            "timer_completion": "dm",
            "_version": 1,
        },
    )
    db_session.add(user)
    await db_session.flush()

    captured: list[dict] = []

    class FakeBot:
        async def fetch_user(self, _id: int):
            class FU:
                id = 600105

                async def send(self, content=None, *, view=None, embed=None):
                    captured.append({"content": content, "has_view": view is not None})

            return FU()

    await redis_client.xadd(
        "d2d:notifications:test_no_batch",
        {
            "user_id": "600105",
            "category": "expedition_event",
            "title": "Scene fired",
            "body": "Pick one:",
            "correlation_id": "c",
            "dedupe_key": "k1",
            "created_at": "now",
            "components": json.dumps(
                [{"custom_id": "expedition:a:s:c", "label": "Go", "style": "primary"}]
            ),
        },
    )
    await redis_client.xadd(
        "d2d:notifications:test_no_batch",
        {
            "user_id": "600105",
            "category": "timer_completion",
            "title": "Training done",
            "body": "Crew gained XP",
            "correlation_id": "c",
            "dedupe_key": "k2",
            "created_at": "now",
        },
    )

    consumer = notifs.NotificationConsumer(
        bot=FakeBot(),
        redis=redis_client,
        stream_key="d2d:notifications:test_no_batch",
        consumer_group="g_no_batch",
        consumer_id="c1",
        batch_window_seconds=0,
        start_id="0",
    )
    await consumer.ensure_group()
    await consumer.process_once(block_ms=200)
    await consumer.flush_pending()

    assert len(captured) == 2
    # Exactly one of the DMs has the View; the other is plain text.
    assert sum(1 for c in captured if c["has_view"]) == 1
    assert sum(1 for c in captured if not c["has_view"]) == 1
