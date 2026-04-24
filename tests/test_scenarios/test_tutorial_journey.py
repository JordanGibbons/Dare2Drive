"""End-to-end scenario test: a new player walks from an empty account to
a minted Ship Title by driving real cog handlers with mocked Discord
interactions against a live test Postgres.

This catches the class of bugs that unit tests miss: missing seed data,
misaligned slot enum values, missing bootstrap rows (e.g. ShipRelease),
stale handler signatures, etc. It's a prototype — if it proves its
keep, split the helpers into tests/test_scenarios/conftest.py and add
more journeys.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select

from bot.cogs.cards import CardsCog
from bot.cogs.hangar import HangarCog
from db.models import (
    Build,
    Card,
    CardSlot,
    HullClass,
    ShipTitle,
    TutorialStep,
    User,
    UserCard,
)
from db.session import async_session

# ──────────────────────────────────────────────────────────────────────
# Discord interaction mocks
# ──────────────────────────────────────────────────────────────────────


@dataclass
class FakeUser:
    id: int
    display_name: str = "TestPlayer"


@dataclass
class RecordedCall:
    method: str
    kwargs: dict[str, Any]


class FakeResponse:
    """Mimics interaction.response — tracks is_done() and records calls."""

    def __init__(self, parent: "FakeInteraction") -> None:
        self._parent = parent
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, content: str | None = None, **kwargs) -> None:
        self._parent.calls.append(
            RecordedCall("response.send_message", {"content": content, **kwargs})
        )
        self._done = True

    async def defer(self, **kwargs) -> None:
        self._parent.calls.append(RecordedCall("response.defer", kwargs))
        self._done = True


class FakeFollowup:
    """Mimics interaction.followup — only records sends."""

    def __init__(self, parent: "FakeInteraction") -> None:
        self._parent = parent

    async def send(self, content: str | None = None, **kwargs) -> None:
        self._parent.calls.append(RecordedCall("followup.send", {"content": content, **kwargs}))


@dataclass
class FakeInteraction:
    user: FakeUser
    guild_id: int = 111111111
    channel_id: int = 222222222
    calls: list[RecordedCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)
        self.command = None  # satisfies interaction_check hooks that inspect this

    # Convenience assertions
    def last_call(self) -> RecordedCall:
        assert self.calls, "no calls recorded on this interaction"
        return self.calls[-1]

    def assert_content_contains(self, needle: str) -> None:
        text_blobs: list[str] = []
        for c in self.calls:
            if c.kwargs.get("content"):
                text_blobs.append(c.kwargs["content"])
            embed = c.kwargs.get("embed")
            if embed is not None:
                text_blobs.append(getattr(embed, "title", "") or "")
                text_blobs.append(getattr(embed, "description", "") or "")
        joined = "\n".join(text_blobs)
        assert needle in joined, f"expected {needle!r} in any response; got:\n{joined}"


def make_interaction(user_id: int) -> FakeInteraction:
    return FakeInteraction(user=FakeUser(id=user_id))


# ──────────────────────────────────────────────────────────────────────
# Seed fixtures (session-scoped: do the expensive setup once)
# ──────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def dispose_shared_engine():
    """Dispose the shared db.session.engine after each test so its connection
    pool doesn't outlive the function-scoped event loop (asyncpg connections
    are bound to the loop they were opened on).
    """
    yield
    from db.session import engine

    await engine.dispose()


@pytest_asyncio.fixture
async def bootstrap_seed() -> None:
    """Idempotent per-test seed — cheap after the first run (existence checks)."""
    from scripts.seed_cards import seed_cards, seed_initial_release

    await seed_cards()
    await seed_initial_release()


# ──────────────────────────────────────────────────────────────────────
# Per-test user fixture — unique id, cleaned up after
# ──────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def tutorial_user(bootstrap_seed):
    """Create a fresh User + default Build + starter UserCards, bypassing /start's view.

    Yields a tuple of (user_id, starter_cards_by_slot). Cleans up on teardown.
    """
    user_id = str(uuid.uuid4().int % 10**15)
    starter_cards_by_slot: dict[str, UserCard] = {}

    async with async_session() as session:
        user = User(
            discord_id=user_id,
            username="TestPlayer",
            hull_class=HullClass.SCOUT,
            currency=0,
            xp=0,
            tutorial_step=TutorialStep.STARTED,
        )
        session.add(user)

        build = Build(
            user_id=user_id,
            name="My Build",
            slots={slot.value: None for slot in CardSlot},
            is_active=True,
            hull_class=HullClass.SCOUT,
        )
        session.add(build)
        await session.flush()

        # Grant one starter card per slot, using the lowest-rarity card in each slot
        for slot in CardSlot:
            result = await session.execute(
                select(Card).where(Card.slot == slot).order_by(Card.rarity).limit(1)
            )
            card = result.scalar_one()
            uc = UserCard(user_id=user_id, card_id=card.id, serial_number=0)
            session.add(uc)
            await session.flush()
            starter_cards_by_slot[slot.value] = uc

        await session.commit()

    yield user_id, starter_cards_by_slot

    # Teardown — reuse the admin reset helper (handles circular FK between builds ↔ ship_titles)
    from bot.cogs.admin import _delete_player_data

    async with async_session() as session:
        u = await session.get(User, user_id)
        if u is not None:
            await _delete_player_data(session, user_id, u)
            await session.commit()


# ──────────────────────────────────────────────────────────────────────
# The scenario
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_player_can_reach_a_minted_ship_title(tutorial_user) -> None:
    """Walk /inventory → /equip (×7) → /build mint and assert a ShipTitle exists."""
    user_id, starters = tutorial_user
    uid_int = int(user_id)

    # Instantiate cogs with a null bot — the scenario never calls bot methods
    hangar = HangarCog(bot=None)  # type: ignore[arg-type]
    cards = CardsCog(bot=None)  # type: ignore[arg-type]

    # 1. /inventory — must show all 7 starter cards, not "empty"
    inv_interaction = make_interaction(uid_int)
    await cards.inventory.callback(cards, inv_interaction)
    for call in inv_interaction.calls:
        content = call.kwargs.get("content") or ""
        assert "inventory is empty" not in content, (
            "Inventory is empty — seed_cards or starter grant broken. "
            f"Calls: {inv_interaction.calls}"
        )

    # 2. /equip each slot with the corresponding starter card
    async with async_session() as session:
        for slot in CardSlot:
            uc = starters[slot.value]
            card = await session.get(Card, uc.card_id)
            equip_interaction = make_interaction(uid_int)
            await hangar.equip.callback(
                hangar, equip_interaction, slot=slot.value, card_name=card.name
            )
            # Expect at least one non-error response
            assert equip_interaction.calls, f"/equip {slot.value}: no response at all"

    # 3. /build mint — must succeed now that all slots are filled + release exists
    mint_interaction = make_interaction(uid_int)
    await hangar.build_mint.callback(hangar, mint_interaction, build=None)

    # Error responses we explicitly want to catch
    for call in mint_interaction.calls:
        content = call.kwargs.get("content") or ""
        assert (
            "No active release found" not in content
        ), "seed_initial_release did not run or did not persist a Genesis ShipRelease"
        assert "Fill all 7 slots" not in content, "equip step did not complete all slots"

    # 4. Assert: a ShipTitle row now exists for this user
    async with async_session() as session:
        result = await session.execute(select(ShipTitle).where(ShipTitle.owner_id == user_id))
        title = result.scalar_one_or_none()
        assert (
            title is not None
        ), f"No ShipTitle was created. mint responses: {mint_interaction.calls}"
        assert title.release_serial > 0
