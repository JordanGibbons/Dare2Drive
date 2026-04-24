"""Shared scaffolding for end-to-end scenario tests.

Drives real cog handlers with mocked Discord interactions against a
live test Postgres. Fixtures build up player state in a pyramid —
each layer reuses the ones below:

    fresh_player  -> user + default Build + 7 starter UserCards
    equipped_player -> fresh_player + all 7 slots filled
    minted_player -> equipped_player + ShipTitle minted
    raceable_player -> minted_player + tutorial_step=RACE (tutorial NPC path)

System-level fixtures:

    active_system -> a Sector row + System row for the test interaction's
                     guild/channel IDs; use when a test needs gameplay
                     commands to be permitted
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest_asyncio
from sqlalchemy import select

from db.models import (
    Build,
    Card,
    CardSlot,
    HullClass,
    Sector,
    System,
    TutorialStep,
    User,
    UserCard,
)
from db.session import async_session

DEFAULT_GUILD_ID = 111111111
DEFAULT_CHANNEL_ID = 222222222


# ──────────────────────────────────────────────────────────────────────
# Discord interaction mocks
# ──────────────────────────────────────────────────────────────────────


@dataclass
class FakeUser:
    id: int
    display_name: str = "TestPlayer"
    bot: bool = False


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
    guild_id: int | None = DEFAULT_GUILD_ID
    channel_id: int | None = DEFAULT_CHANNEL_ID
    calls: list[RecordedCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)
        self.command = None

    def last_call(self) -> RecordedCall:
        assert self.calls, "no calls recorded on this interaction"
        return self.calls[-1]

    def all_content(self) -> str:
        """Flatten every text blob sent on this interaction for substring checks."""
        blobs: list[str] = []
        for c in self.calls:
            content = c.kwargs.get("content")
            if content:
                blobs.append(str(content))
            embed = c.kwargs.get("embed")
            if embed is not None:
                blobs.append(str(getattr(embed, "title", "") or ""))
                blobs.append(str(getattr(embed, "description", "") or ""))
        return "\n".join(blobs)


def make_interaction(
    user_id: int,
    guild_id: int | None = DEFAULT_GUILD_ID,
    channel_id: int | None = DEFAULT_CHANNEL_ID,
    display_name: str = "TestPlayer",
) -> FakeInteraction:
    return FakeInteraction(
        user=FakeUser(id=user_id, display_name=display_name),
        guild_id=guild_id,
        channel_id=channel_id,
    )


# ──────────────────────────────────────────────────────────────────────
# Engine lifecycle fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def dispose_shared_engine():
    """Dispose the shared db.session.engine after each test so its connection
    pool doesn't outlive the function-scoped event loop (asyncpg connections
    are bound to the loop they were opened on)."""
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
# Player fixtures (pyramid — each layer builds on the previous)
# ──────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def fresh_player(bootstrap_seed):
    """User + default Build + 7 starter UserCards (one per slot).

    Bypasses /start's Discord view. Yields (user_id, starter_ucs_by_slot).
    Teardown reuses _delete_player_data for the circular FK between
    builds ↔ ship_titles.
    """
    user_id = str(uuid.uuid4().int % 10**15)
    starter_ucs_by_slot: dict[str, UserCard] = {}

    async with async_session() as session:
        user = User(
            discord_id=user_id,
            username=f"Test_{user_id[-6:]}",
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

        for slot in CardSlot:
            result = await session.execute(
                select(Card).where(Card.slot == slot).order_by(Card.rarity).limit(1)
            )
            card = result.scalar_one()
            uc = UserCard(user_id=user_id, card_id=card.id, serial_number=0)
            session.add(uc)
            await session.flush()
            starter_ucs_by_slot[slot.value] = uc

        await session.commit()

    yield user_id, starter_ucs_by_slot

    from bot.cogs.admin import _delete_player_data

    async with async_session() as session:
        u = await session.get(User, user_id)
        if u is not None:
            await _delete_player_data(session, user_id, u)
            await session.commit()


@pytest_asyncio.fixture
async def equipped_player(fresh_player):
    """fresh_player with all 7 slots filled (direct DB write, not /equip)."""
    user_id, starters = fresh_player

    async with async_session() as session:
        result = await session.execute(
            select(Build).where(Build.user_id == user_id, Build.is_active)
        )
        build = result.scalar_one()
        build.slots = {slot: str(uc.id) for slot, uc in starters.items()}
        await session.commit()

    return user_id, starters


@pytest_asyncio.fixture
async def minted_player(equipped_player):
    """equipped_player with a minted ShipTitle. Drives the real /build mint
    handler. /build mint is universe-wide (build management isn't sector-gated),
    so no active_system dependency is needed here."""
    user_id, starters = equipped_player
    from bot.cogs.hangar import HangarCog

    hangar = HangarCog(bot=None)  # type: ignore[arg-type]
    interaction = make_interaction(int(user_id))
    await hangar.build_mint.callback(hangar, interaction, build=None)

    return user_id, starters


@pytest_asyncio.fixture
async def raceable_player(minted_player):
    """minted_player with tutorial_step=RACE so /race triggers the NPC path."""
    user_id, starters = minted_player
    async with async_session() as session:
        user = await session.get(User, user_id)
        user.tutorial_step = TutorialStep.RACE
        await session.commit()

    return user_id, starters


# ──────────────────────────────────────────────────────────────────────
# System/Sector fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def active_system():
    """Create a Sector (guild) + System (channel) row matching the default
    interaction guild_id/channel_id. Cleaned up on teardown."""
    guild_id = str(DEFAULT_GUILD_ID)
    channel_id = str(DEFAULT_CHANNEL_ID)

    async with async_session() as session:
        sector = Sector(
            guild_id=guild_id,
            name="Test Sector",
            owner_discord_id="999999999",
        )
        session.add(sector)
        system = System(
            channel_id=channel_id,
            sector_id=guild_id,
            name="test-system",
        )
        session.add(system)
        await session.commit()

    yield guild_id, channel_id

    async with async_session() as session:
        from sqlalchemy import delete

        await session.execute(delete(System).where(System.channel_id == channel_id))
        await session.execute(delete(Sector).where(Sector.guild_id == guild_id))
        await session.commit()
