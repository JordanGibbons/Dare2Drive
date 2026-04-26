"""Notification emission to Redis Streams."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

import redis.asyncio as redis_async

from config.logging import get_logger
from config.settings import settings
from scheduler.dispatch import NotificationRequest

log = get_logger(__name__)

DEFAULT_STREAM_KEY = "d2d:notifications"

_client: redis_async.Redis | None = None


def get_redis_client() -> redis_async.Redis:
    """Return the process-local async Redis client (lazy-init)."""
    global _client
    if _client is None:
        _client = redis_async.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


def _to_stream_fields(n: NotificationRequest) -> dict[str, str]:
    d = asdict(n)
    d["created_at"] = datetime.now(timezone.utc).isoformat()
    return d


async def emit_notification(
    n: NotificationRequest,
    *,
    client: redis_async.Redis | None = None,
    stream_key: str | None = None,
    maxlen: int | None = None,
) -> str:
    """XADD a NotificationRequest to the Redis stream. Returns the entry id."""
    c = client or get_redis_client()
    key = stream_key or DEFAULT_STREAM_KEY
    cap = maxlen if maxlen is not None else settings.NOTIFICATION_STREAM_MAXLEN
    entry_id = await c.xadd(key, _to_stream_fields(n), maxlen=cap, approximate=False)
    log.info(
        "notification_emitted user_id=%s category=%s correlation_id=%s entry_id=%s",
        n.user_id,
        n.category,
        n.correlation_id,
        entry_id,
    )
    return entry_id
