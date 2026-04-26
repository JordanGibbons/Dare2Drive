"""Backfill crew_members.current_activity from existing crew_assignments.

Run this **after** alembic upgrade for 0003_phase2a_scheduler. Idempotent:
running multiple times is safe -- the WHERE clause restricts to crew
that are still 'idle' (the default) and have a corresponding assignment row.

Usage:
    python -m scripts.backfills.0003_crew_current_activity
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from config.logging import get_logger, setup_logging
from db.session import async_session

log = get_logger(__name__)


BACKFILL_SQL = text("""
    UPDATE crew_members AS cm
    SET current_activity = 'on_build',
        current_activity_id = ca.build_id
    FROM crew_assignments AS ca
    WHERE ca.crew_id = cm.id
      AND cm.current_activity = 'idle'
    RETURNING cm.id;
    """)


async def main() -> int:
    setup_logging()
    async with async_session() as session, session.begin():
        result = await session.execute(BACKFILL_SQL)
        rows = list(result)
    log.info("backfill_complete count=%d", len(rows))
    return len(rows)


if __name__ == "__main__":
    asyncio.run(main())
