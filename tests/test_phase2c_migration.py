"""Phase 2c — migration round-trip + constraint presence tests."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://dare2drive:dare2drive@localhost:5432/dare2drive",
)


@pytest.mark.asyncio
async def test_build_crew_assignments_table_exists():
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        result = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("build_crew_assignments")
        )
        assert result is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_build_crew_assignments_has_required_columns():
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sync_conn: {
                c["name"] for c in inspect(sync_conn).get_columns("build_crew_assignments")
            }
        )
        assert {"build_id", "crew_id", "archetype", "assigned_at"} <= cols
    await engine.dispose()


@pytest.mark.asyncio
async def test_build_crew_assignments_unique_crew_id():
    """A crew member is on at most one ship at a time."""
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        result = await conn.execute(text("""
                SELECT COUNT(*) FROM pg_indexes
                WHERE tablename = 'build_crew_assignments'
                  AND indexdef ILIKE '%UNIQUE%'
                  AND indexdef ILIKE '%crew_id%'
                """))
        count = result.scalar_one()
        assert count >= 1, "missing UNIQUE(crew_id) index"
    await engine.dispose()


@pytest.mark.asyncio
async def test_build_crew_assignments_pk_build_archetype():
    """One slot per archetype per build."""
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        pk_cols = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_pk_constraint("build_crew_assignments")[
                "constrained_columns"
            ]
        )
        assert set(pk_cols) == {"build_id", "archetype"}
    await engine.dispose()
