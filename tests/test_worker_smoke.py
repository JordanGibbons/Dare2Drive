"""Smoke test for scheduler.worker — start, run a tick, shut down cleanly."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_worker_starts_and_stops_within_timeout():
    from scheduler.worker import run

    shutdown = asyncio.Event()

    async def _stop_after():
        await asyncio.sleep(0.5)
        shutdown.set()

    runner = asyncio.create_task(run(shutdown_event=shutdown))
    stopper = asyncio.create_task(_stop_after())

    await asyncio.wait_for(runner, timeout=5.0)
    await stopper
