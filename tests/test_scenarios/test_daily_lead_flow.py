"""Integration: get_or_roll_today_lead idempotence + recruit_from_daily_lead claim semantics."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from db.models import CrewDailyLead, CrewMember, HullClass, User


@pytest_asyncio.fixture
async def lead_user(db_session):
    u = User(
        discord_id="222111111",
        username="dailytest",
        hull_class=HullClass.SKIRMISHER,
        currency=0,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_get_or_roll_is_idempotent_then_hire_succeeds(lead_user, db_session):
    from engine.crew_recruit import (
        get_or_roll_today_lead,
        recruit_crew_from_daily_lead,
    )

    lead1 = await get_or_roll_today_lead(db_session, lead_user)
    lead2 = await get_or_roll_today_lead(db_session, lead_user)
    assert lead1.first_name == lead2.first_name

    member = await recruit_crew_from_daily_lead(db_session, lead_user, lead1)
    assert member.first_name == lead1.first_name

    res = await db_session.execute(
        select(CrewMember).where(CrewMember.user_id == lead_user.discord_id)
    )
    assert len(list(res.scalars().all())) == 1


@pytest.mark.asyncio
async def test_next_day_rolls_fresh_lead(lead_user, db_session):
    from engine.crew_recruit import get_or_roll_today_lead

    today = date(2026, 4, 24)
    tomorrow = today + timedelta(days=1)

    lead_today = await get_or_roll_today_lead(db_session, lead_user, today=today)
    lead_tomorrow = await get_or_roll_today_lead(db_session, lead_user, today=tomorrow)

    assert lead_today.rolled_for_date != lead_tomorrow.rolled_for_date
    res = await db_session.execute(
        select(CrewDailyLead).where(CrewDailyLead.user_id == lead_user.discord_id)
    )
    assert len(list(res.scalars().all())) == 2
