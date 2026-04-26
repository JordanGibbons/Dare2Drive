"""Bot-side Redis-stream consumer with rate-limit + batching for DM delivery."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass

import discord
import redis.asyncio as redis_async

from api.metrics import notifications_total
from config.logging import get_logger
from config.settings import settings
from db.models import User
from db.session import async_session

log = get_logger(__name__)

DEFAULT_STREAM_KEY = "d2d:notifications"
DEFAULT_CONSUMER_GROUP = "d2d-bot"


@dataclass
class _PendingItem:
    user_id: str
    category: str
    title: str
    body: str
    entry_id: str
    received_at: float


class NotificationConsumer:
    """Reads notifications from a Redis stream, applies rate-limit + batching, sends DMs."""

    def __init__(
        self,
        *,
        bot: discord.Client,
        redis: redis_async.Redis,
        stream_key: str = DEFAULT_STREAM_KEY,
        consumer_group: str = DEFAULT_CONSUMER_GROUP,
        consumer_id: str = "bot-1",
        batch_window_seconds: float | None = None,
        rate_limit_per_hour: int | None = None,
    ) -> None:
        self.bot = bot
        self.redis = redis
        self.stream_key = stream_key
        self.consumer_group = consumer_group
        self.consumer_id = consumer_id
        self.batch_window_seconds = (
            batch_window_seconds
            if batch_window_seconds is not None
            else settings.NOTIFICATION_BATCH_WINDOW_SECONDS
        )
        self.rate_limit_per_hour = (
            rate_limit_per_hour
            if rate_limit_per_hour is not None
            else settings.NOTIFICATION_RATE_LIMIT_PER_HOUR
        )
        self._buffer: dict[str, list[_PendingItem]] = defaultdict(list)
        self._rate_buckets: dict[tuple[str, int], int] = defaultdict(int)
        self._stop = asyncio.Event()

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(
                self.stream_key, self.consumer_group, id="0", mkstream=True
            )
        except redis_async.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def run(self) -> None:
        """Run forever, until stop() is called."""
        await self.ensure_group()
        while not self._stop.is_set():
            try:
                await self.process_once(block_ms=2000)
                await self.flush_pending()
            except Exception:
                log.exception("notification consumer loop error")
                await asyncio.sleep(1)

    def stop(self) -> None:
        self._stop.set()

    async def process_once(self, *, block_ms: int = 2000) -> None:
        msgs = await self.redis.xreadgroup(
            self.consumer_group,
            self.consumer_id,
            {self.stream_key: ">"},
            count=50,
            block=block_ms,
        )
        if not msgs:
            return
        for _stream, entries in msgs:
            for entry_id, fields in entries:
                user_id = fields.get("user_id")
                if not user_id:
                    await self.redis.xack(self.stream_key, self.consumer_group, entry_id)
                    continue
                self._buffer[user_id].append(
                    _PendingItem(
                        user_id=user_id,
                        category=fields.get("category", "timer_completion"),
                        title=fields.get("title", ""),
                        body=fields.get("body", ""),
                        entry_id=entry_id,
                        received_at=time.monotonic(),
                    )
                )

    async def flush_pending(self) -> None:
        now = time.monotonic()
        for user_id, items in list(self._buffer.items()):
            ready = [it for it in items if (now - it.received_at) >= self.batch_window_seconds]
            if not ready:
                continue
            await self._deliver_batch(user_id, ready)
            self._buffer[user_id] = [it for it in items if it not in ready]
            if not self._buffer[user_id]:
                del self._buffer[user_id]

    async def _deliver_batch(self, user_id: str, items: list[_PendingItem]) -> None:
        async with async_session() as session:
            user = await session.get(User, user_id)
        if user is None:
            for it in items:
                await self.redis.xack(self.stream_key, self.consumer_group, it.entry_id)
                notifications_total.labels(category=it.category, result="user_missing").inc()
            return

        prefs = dict(user.notification_prefs or {})
        # Filter out opted-out categories.
        deliver, drop = [], []
        for it in items:
            if prefs.get(it.category, "dm") == "off":
                drop.append(it)
            else:
                deliver.append(it)
        for it in drop:
            await self.redis.xack(self.stream_key, self.consumer_group, it.entry_id)
            notifications_total.labels(category=it.category, result="opted_out").inc()

        if not deliver:
            return

        # Rate limit (per-user, per hour bucket).
        hour_bucket = int(time.time() // 3600)
        sent_this_hour = self._rate_buckets[(user_id, hour_bucket)]
        room = max(0, self.rate_limit_per_hour - sent_this_hour)
        to_send = deliver[:room] if room < len(deliver) else deliver
        rate_dropped = deliver[room:] if room < len(deliver) else []
        for it in rate_dropped:
            await self.redis.xack(self.stream_key, self.consumer_group, it.entry_id)
            notifications_total.labels(category=it.category, result="rate_limited").inc()

        if not to_send:
            return

        try:
            discord_user = await self.bot.fetch_user(int(user_id))
        except Exception:
            log.exception("fetch_user failed user_id=%s", user_id)
            return

        # Merge titles/bodies into one DM.
        merged = "\n\n".join(f"**{it.title}**\n{it.body}" for it in to_send)
        try:
            await discord_user.send(merged)
            for it in to_send:
                await self.redis.xack(self.stream_key, self.consumer_group, it.entry_id)
                notifications_total.labels(category=it.category, result="delivered").inc()
            self._rate_buckets[(user_id, hour_bucket)] += len(to_send)
        except discord.Forbidden:
            for it in to_send:
                await self.redis.xack(self.stream_key, self.consumer_group, it.entry_id)
                notifications_total.labels(category=it.category, result="dm_closed").inc()
        except Exception:
            log.exception("DM send failed user_id=%s", user_id)
            for it in to_send:
                notifications_total.labels(category=it.category, result="failed").inc()
            # don't XACK transient failures — let XPENDING reclaim later.
