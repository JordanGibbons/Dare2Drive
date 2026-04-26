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
