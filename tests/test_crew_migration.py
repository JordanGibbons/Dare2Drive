"""Round-trip test for the 0002 crew migration."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from config.settings import settings


@pytest.mark.asyncio
async def test_crew_tables_exist_after_migration():
    """crew_members, crew_assignments, crew_daily_leads all exist."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return set(insp.get_table_names())

        names = await conn.run_sync(_inspect)
    await engine.dispose()
    assert {"crew_members", "crew_assignments", "crew_daily_leads"} <= names


@pytest.mark.asyncio
async def test_crew_member_unique_constraint():
    """Unique on (user_id, first_name, last_name, callsign)."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [uc["name"] for uc in insp.get_unique_constraints("crew_members")]

        uqs = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "uq_crew_members_user_name" in uqs


@pytest.mark.asyncio
async def test_crew_assignment_unique_crew_id():
    """crew_id is unique (enforces one-crew-one-build)."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            uqs = insp.get_unique_constraints("crew_assignments")
            indexes = insp.get_indexes("crew_assignments")
            return uqs, indexes

        uqs, indexes = await conn.run_sync(_inspect)
    await engine.dispose()
    has_uniq_crew_id = any(set(uc["column_names"]) == {"crew_id"} for uc in uqs) or any(
        set(i["column_names"]) == {"crew_id"} and i.get("unique") for i in indexes
    )
    assert has_uniq_crew_id


@pytest.mark.asyncio
async def test_crew_assignment_unique_build_archetype():
    """(build_id, archetype) is unique."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [uc["name"] for uc in insp.get_unique_constraints("crew_assignments")]

        uqs = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "uq_crew_assignments_build_archetype" in uqs
