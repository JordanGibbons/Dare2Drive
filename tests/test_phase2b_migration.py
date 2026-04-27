"""Phase 2b migration: tables exist, columns exist, partial unique index exists."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from config.settings import settings

pytestmark = pytest.mark.asyncio


async def test_phase2b_tables_exist_after_migration():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return set(insp.get_table_names())

        tables = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "expeditions" in tables
    assert "expedition_crew_assignments" in tables


async def test_builds_has_current_activity_columns():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return {c["name"] for c in insp.get_columns("builds")}

        cols = await conn.run_sync(_inspect)
    await engine.dispose()
    assert {"current_activity", "current_activity_id"} <= cols


async def test_crew_members_has_injured_until_column():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return {c["name"] for c in insp.get_columns("crew_members")}

        cols = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "injured_until" in cols


async def test_expedition_active_per_build_partial_unique_index_exists(db_session):
    """Postgres-side: the partial unique index is present."""
    result = await db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'expeditions' "
            "AND indexname = 'ix_expeditions_active_per_build'"
        )
    )
    indexdef = result.scalar_one_or_none()
    assert indexdef is not None
    assert "(state = 'active'" in indexdef.lower() or "where (state = 'active'" in indexdef.lower()


async def test_expedition_state_enum_in_postgres(db_session):
    result = await db_session.execute(
        text("SELECT unnest(enum_range(NULL::expedition_state))::text")
    )
    values = {row[0] for row in result}
    assert values == {"active", "completed", "failed"}


async def test_build_activity_enum_in_postgres(db_session):
    result = await db_session.execute(text("SELECT unnest(enum_range(NULL::build_activity))::text"))
    values = {row[0] for row in result}
    assert values == {"idle", "on_expedition"}


async def test_crew_activity_includes_on_expedition(db_session):
    # Prior migrations named this enum 'crewactivity' (no underscore).
    result = await db_session.execute(text("SELECT unnest(enum_range(NULL::crewactivity))::text"))
    values = {row[0] for row in result}
    assert "on_expedition" in values


async def test_job_type_includes_expedition_jobs(db_session):
    # Prior migrations named this enum 'jobtype' (no underscore).
    result = await db_session.execute(text("SELECT unnest(enum_range(NULL::jobtype))::text"))
    values = {row[0] for row in result}
    assert {
        "expedition_event",
        "expedition_auto_resolve",
        "expedition_resolve",
        "expedition_complete",
    } <= values


async def test_reward_source_type_includes_expedition_outcome(db_session):
    # Prior migrations named this enum 'rewardsourcetype' (no underscore).
    result = await db_session.execute(
        text("SELECT unnest(enum_range(NULL::rewardsourcetype))::text")
    )
    values = {row[0] for row in result}
    assert "expedition_outcome" in values
