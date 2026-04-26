"""Worker process entry point: tracing, metrics, run_forever loop."""

from __future__ import annotations

import asyncio
import signal

from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from prometheus_client import start_http_server
from sqlalchemy.ext.asyncio import async_sessionmaker

from config.logging import get_logger, setup_logging
from config.settings import settings
from config.tracing import init_tracing
from db.session import engine
from scheduler import dispatch as _dispatch_module  # noqa: F401 — registers handlers
from scheduler.engine import run_forever as run_engine_forever
from scheduler.jobs import accrual_tick as _accrual_module  # noqa: F401
from scheduler.jobs import timer_complete as _timer_complete_module  # noqa: F401
from scheduler.recovery import run_forever as run_recovery_forever

log = get_logger(__name__)


async def run(*, shutdown_event: asyncio.Event | None = None) -> None:
    """Run the worker: start engine and recovery loops concurrently until shutdown."""
    if shutdown_event is None:
        shutdown_event = asyncio.Event()

    sm = async_sessionmaker(bind=engine, expire_on_commit=False)

    engine_task = asyncio.create_task(
        run_engine_forever(sm, _dispatch_module.dispatch, shutdown_event=shutdown_event),
        name="scheduler.engine",
    )
    recovery_task = asyncio.create_task(
        run_recovery_forever(sm, shutdown_event=shutdown_event),
        name="scheduler.recovery",
    )
    log.info("worker_started tick_interval_s=%d", settings.SCHEDULER_TICK_INTERVAL_SECONDS)

    try:
        await asyncio.gather(engine_task, recovery_task)
    finally:
        log.info("worker_stopped")


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event) -> None:
    def _trigger():
        log.info("shutdown_signal_received")
        shutdown.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _trigger)
        except NotImplementedError:
            # Windows: signal handlers run in the OS signal context, not the
            # event loop thread. Marshal the trigger back via call_soon_threadsafe
            # so asyncio.Event.set() runs in the loop thread.
            signal.signal(sig, lambda *a: loop.call_soon_threadsafe(_trigger))


async def _main() -> None:
    setup_logging()
    init_tracing("Dare2Drive-Worker")
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

    start_http_server(8002)
    log.info("worker_metrics_server_started port=8002")

    shutdown = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), shutdown)

    await run(shutdown_event=shutdown)


def cli() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    cli()
