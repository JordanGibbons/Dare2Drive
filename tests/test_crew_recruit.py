"""Unit tests for engine.crew_recruit."""

from __future__ import annotations

import random
from collections import Counter
from datetime import date

import pytest
import pytest_asyncio

from db.models import CrewArchetype, HullClass, Rarity, User
from engine.crew_recruit import (
    CrewRollResult,
    InsufficientCreditsError,
    LeadAlreadyClaimedError,
    get_or_roll_today_lead,
    recruit_crew_from_daily_lead,
    recruit_crew_from_dossier,
    roll_crew,
)


class TestRollCrew:
    def test_archetype_is_uniform_over_10k_rolls(self):
        random.seed(42)
        counts = Counter()
        for _ in range(10_000):
            r = roll_crew(weights={"common": 100}, existing_names=set())
            counts[r.archetype] += 1
        # Each archetype should land roughly 2000 ± 300 at 10k samples (χ² ballpark)
        for arch in CrewArchetype:
            assert 1700 < counts[arch.value] < 2300

    def test_rarity_follows_weights_within_tolerance(self):
        random.seed(42)
        weights = {"common": 0, "uncommon": 0, "rare": 40, "epic": 40, "legendary": 17, "ghost": 3}
        counts = Counter()
        for _ in range(10_000):
            r = roll_crew(weights=weights, existing_names=set())
            counts[r.rarity] += 1
        # Expected: rare ~4000, epic ~4000, legendary ~1700, ghost ~300
        assert 3700 < counts["rare"] < 4300
        assert 3700 < counts["epic"] < 4300
        assert 1500 < counts["legendary"] < 1900
        assert 200 < counts["ghost"] < 400
        assert counts.get("common", 0) == 0
        assert counts.get("uncommon", 0) == 0

    def test_name_collision_reroll(self):
        random.seed(42)
        # Simpler assertion: rolling 500 times with fully-growing existing_names
        # produces 500 unique names (name collision logic rerolls or appends suffix).
        existing: set[tuple[str, str, str]] = set()
        for _ in range(500):
            r = roll_crew(weights={"common": 100}, existing_names=existing)
            key = (r.first_name, r.last_name, r.callsign)
            assert key not in existing
            existing.add(key)


class TestCrewRollResultShape:
    def test_result_has_expected_fields(self):
        r = roll_crew(weights={"common": 100}, existing_names=set())
        assert isinstance(r, CrewRollResult)
        assert r.archetype in {a.value for a in CrewArchetype}
        assert r.rarity in {ra.value for ra in Rarity}
        assert r.first_name and r.last_name and r.callsign


@pytest_asyncio.fixture
async def sample_user_with_creds(db_session):
    user = User(
        discord_id="777777777",
        username="testpilot",
        hull_class=HullClass.SKIRMISHER,
        currency=2000,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_recruit_from_dossier_deducts_creds_and_creates_crew(
    db_session, sample_user_with_creds
):
    user = sample_user_with_creds
    member = await recruit_crew_from_dossier(db_session, user, "dossier")
    assert user.currency == 1500  # 2000 - 500
    assert member.id is not None
    assert member.archetype.value in {a.value for a in CrewArchetype}


@pytest.mark.asyncio
async def test_recruit_from_dossier_insufficient_creds_raises(db_session):
    user = User(
        discord_id="888888888",
        username="broke",
        hull_class=HullClass.SKIRMISHER,
        currency=10,
    )
    db_session.add(user)
    await db_session.flush()
    with pytest.raises(InsufficientCreditsError):
        await recruit_crew_from_dossier(db_session, user, "dossier")


@pytest.mark.asyncio
async def test_get_or_roll_today_lead_is_idempotent(db_session, sample_user_with_creds):
    user = sample_user_with_creds
    today = date(2026, 4, 24)
    lead1 = await get_or_roll_today_lead(db_session, user, today=today)
    lead2 = await get_or_roll_today_lead(db_session, user, today=today)
    assert (lead1.user_id, lead1.rolled_for_date) == (lead2.user_id, lead2.rolled_for_date)
    assert lead1.first_name == lead2.first_name  # same roll returned


@pytest.mark.asyncio
async def test_recruit_from_daily_lead_stamps_claimed(db_session, sample_user_with_creds):
    user = sample_user_with_creds
    lead = await get_or_roll_today_lead(db_session, user)
    member = await recruit_crew_from_daily_lead(db_session, user, lead)
    assert lead.claimed_at is not None
    assert member.first_name == lead.first_name


@pytest.mark.asyncio
async def test_recruit_from_daily_lead_twice_raises(db_session, sample_user_with_creds):
    user = sample_user_with_creds
    lead = await get_or_roll_today_lead(db_session, user)
    await recruit_crew_from_daily_lead(db_session, user, lead)
    with pytest.raises(LeadAlreadyClaimedError):
        await recruit_crew_from_daily_lead(db_session, user, lead)
