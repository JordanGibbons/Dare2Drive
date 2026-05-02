"""Tests for scheduler.notifications — Redis Streams XADD."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_emit_notification_xadds_to_stream(redis_client):
    from scheduler.notifications import NotificationRequest, emit_notification

    n = NotificationRequest(
        user_id="555",
        category="timer_completion",
        title="Training complete",
        body="Alice gained 200 XP",
        correlation_id="11111111-1111-1111-1111-111111111111",
        dedupe_key="timer:abc",
    )
    await emit_notification(n, client=redis_client, stream_key="d2d:notifications:test")

    entries = await redis_client.xrange("d2d:notifications:test", count=10)
    assert len(entries) == 1
    _, fields = entries[0]
    assert fields["user_id"] == "555"
    assert fields["category"] == "timer_completion"
    assert fields["title"] == "Training complete"
    assert fields["correlation_id"] == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_emit_notification_serializes_components(redis_client):
    """Buttons attached to a NotificationRequest round-trip through the stream as JSON."""
    import json

    from scheduler.dispatch import NotificationButton
    from scheduler.notifications import NotificationRequest, emit_notification

    n = NotificationRequest(
        user_id="900",
        category="expedition_event",
        title="Pirate skiff",
        body="Choose:",
        correlation_id="cor",
        dedupe_key="dk",
        components=[
            NotificationButton(custom_id="expedition:abc:s1:c1", label="Run", style="primary"),
            NotificationButton(custom_id="expedition:abc:s1:c2", label="Fight", style="danger"),
        ],
    )
    await emit_notification(n, client=redis_client, stream_key="d2d:notifications:components")

    entries = await redis_client.xrange("d2d:notifications:components", count=10)
    assert len(entries) == 1
    _, fields = entries[0]
    decoded = json.loads(fields["components"])
    assert decoded == [
        {"custom_id": "expedition:abc:s1:c1", "label": "Run", "style": "primary"},
        {"custom_id": "expedition:abc:s1:c2", "label": "Fight", "style": "danger"},
    ]


@pytest.mark.asyncio
async def test_emit_notification_serializes_embed_fields(redis_client):
    """Embed fields round-trip through the stream as JSON, parallel to components."""
    import json

    from scheduler.dispatch import NotificationEmbedField
    from scheduler.notifications import NotificationRequest, emit_notification

    n = NotificationRequest(
        user_id="902",
        category="expedition_event",
        title="t",
        body="b",
        correlation_id="c",
        dedupe_key="k",
        embed_fields=[
            NotificationEmbedField(name="A.", value="Run for it."),
            NotificationEmbedField(name="B.", value="Fight.", inline=True),
        ],
    )
    await emit_notification(n, client=redis_client, stream_key="d2d:notifications:embed_fields")
    entries = await redis_client.xrange("d2d:notifications:embed_fields", count=10)
    decoded = json.loads(entries[0][1]["embed_fields"])
    assert decoded == [
        {"name": "A.", "value": "Run for it.", "inline": False},
        {"name": "B.", "value": "Fight.", "inline": True},
    ]


@pytest.mark.asyncio
async def test_emit_notification_omits_components_when_absent(redis_client):
    """Notifications without buttons must not write a `components` field at all."""
    from scheduler.notifications import NotificationRequest, emit_notification

    n = NotificationRequest(
        user_id="901",
        category="timer_completion",
        title="t",
        body="b",
        correlation_id="c",
        dedupe_key="k",
    )
    await emit_notification(n, client=redis_client, stream_key="d2d:notifications:plain")
    entries = await redis_client.xrange("d2d:notifications:plain", count=10)
    assert "components" not in entries[0][1]


@pytest.mark.asyncio
async def test_emit_notification_respects_maxlen(redis_client):
    from scheduler.notifications import NotificationRequest, emit_notification

    for i in range(20):
        await emit_notification(
            NotificationRequest(
                user_id="x",
                category="timer_completion",
                title=str(i),
                body="b",
                correlation_id="c",
                dedupe_key=str(i),
            ),
            client=redis_client,
            stream_key="d2d:notifications:cap",
            maxlen=5,
            approximate=False,
        )

    length = await redis_client.xlen("d2d:notifications:cap")
    assert length == 5
