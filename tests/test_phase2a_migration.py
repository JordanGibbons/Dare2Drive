"""Round-trip + content tests for the 0003 phase 2a migration."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from config.settings import settings


@pytest.mark.asyncio
async def test_phase2a_tables_exist_after_migration():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return set(insp.get_table_names())

        names = await conn.run_sync(_inspect)
    await engine.dispose()
    assert {"scheduled_jobs", "timers", "station_assignments", "reward_ledger"} <= names


@pytest.mark.asyncio
async def test_crew_members_has_current_activity_column():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [c["name"] for c in insp.get_columns("crew_members")]

        cols = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "current_activity" in cols
    assert "current_activity_id" in cols


@pytest.mark.asyncio
async def test_users_has_notification_prefs_column():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [c["name"] for c in insp.get_columns("users")]

        cols = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "notification_prefs" in cols


@pytest.mark.asyncio
async def test_reward_ledger_unique_source_constraint():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [uc["name"] for uc in insp.get_unique_constraints("reward_ledger")]

        uqs = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "ux_reward_ledger_source" in uqs


@pytest.mark.asyncio
async def test_timers_partial_unique_indexes():
    """Verify partial unique indexes for one-active-research / one-active-build per user."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            return [i["name"] for i in insp.get_indexes("timers")]

        idx_names = await conn.run_sync(_inspect)
    await engine.dispose()
    assert "ux_timers_one_research_active" in idx_names
    assert "ux_timers_one_ship_build_active" in idx_names


@pytest.mark.asyncio
async def test_crew_backfill_marks_assigned_crew_on_build(db_session):
    """Existing CrewAssignment rows produce current_activity='on_build' after backfill."""
    import uuid as _uuid

    from db.models import (
        Build,
        CrewActivity,
        CrewArchetype,
        CrewAssignment,
        CrewMember,
        HullClass,
        Rarity,
        User,
    )

    user = User(
        discord_id="555111222",
        username="backfill_test",
        hull_class=HullClass.HAULER,
    )
    db_session.add(user)
    await db_session.flush()

    build = Build(
        id=_uuid.uuid4(), user_id=user.discord_id, name="bf_build", hull_class=HullClass.HAULER
    )
    db_session.add(build)
    await db_session.flush()

    crew = CrewMember(
        id=_uuid.uuid4(),
        user_id=user.discord_id,
        first_name="Bee",
        last_name="Eff",
        callsign="Backfill",
        archetype=CrewArchetype.PILOT,
        rarity=Rarity.COMMON,
    )
    db_session.add(crew)
    await db_session.flush()

    db_session.add(
        CrewAssignment(
            id=_uuid.uuid4(),
            crew_id=crew.id,
            build_id=build.id,
            archetype=CrewArchetype.PILOT,
        )
    )
    await db_session.flush()

    # Ensure current_activity is still the default 'idle'.
    assert crew.current_activity == CrewActivity.IDLE

    # Run the backfill SQL inline (the script's same statement).
    from scripts.backfills import _0003_crew_current_activity as bf  # noqa

    await db_session.execute(bf.BACKFILL_SQL)

    # Refresh the cached instance so we re-fetch from DB after the raw UPDATE.
    await db_session.refresh(crew)
    assert crew.current_activity == CrewActivity.ON_BUILD
    assert crew.current_activity_id == build.id
