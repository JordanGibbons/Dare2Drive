"""SQLAlchemy async models for Dare2Drive (Salvage-Pulp universe)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ──────────── Enums ────────────


class HullClass(str, enum.Enum):
    HAULER = "hauler"
    SKIRMISHER = "skirmisher"
    SCOUT = "scout"


class RaceFormat(str, enum.Enum):
    SPRINT = "sprint"
    ENDURANCE = "endurance"
    GAUNTLET = "gauntlet"


class ShipStatus(str, enum.Enum):
    ACTIVE = "active"
    SCRAPPED = "scrapped"


class TutorialStep(str, enum.Enum):
    """Tracks player progress through the onboarding tutorial."""

    STARTED = "started"
    INVENTORY = "inventory"
    INSPECT = "inspect"
    EQUIP = "equip"
    MINT = "mint"
    GARAGE = "garage"  # internal name retained; UI surfaces /hangar
    RACE = "race"
    PACK = "pack"
    COMPLETE = "complete"


class CardSlot(str, enum.Enum):
    REACTOR = "reactor"
    DRIVE = "drive"
    THRUSTERS = "thrusters"
    STABILIZERS = "stabilizers"
    HULL = "hull"
    OVERDRIVE = "overdrive"
    RETROS = "retros"


class Rarity(str, enum.Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"
    GHOST = "ghost"


# ──────────── Multi-tenant Models ────────────


class Sector(Base):
    __tablename__ = "sectors"

    guild_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    flavor_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    system_cap: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")
    owner_discord_id: Mapped[str] = mapped_column(String(20), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    systems: Mapped[list[System]] = relationship(back_populates="sector", lazy="selectin")


class System(Base):
    __tablename__ = "systems"

    channel_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    sector_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("sectors.guild_id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    flavor_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    enabled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sector: Mapped[Sector] = relationship(back_populates="systems")


# ──────────── Player Models ────────────


class User(Base):
    __tablename__ = "users"

    discord_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    hull_class: Mapped[HullClass] = mapped_column(
        Enum(HullClass, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    currency: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tutorial_step: Mapped[TutorialStep] = mapped_column(
        Enum(TutorialStep, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TutorialStep.STARTED,
    )
    last_daily: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user_cards: Mapped[list[UserCard]] = relationship(back_populates="user", lazy="selectin")
    builds: Mapped[list[Build]] = relationship(back_populates="user", lazy="selectin")
    market_listings: Mapped[list[MarketListing]] = relationship(
        back_populates="seller", lazy="selectin"
    )
    wreck_logs: Mapped[list[WreckLog]] = relationship(back_populates="user", lazy="selectin")


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    slot: Mapped[CardSlot] = mapped_column(
        Enum(CardSlot, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    rarity: Mapped[Rarity] = mapped_column(
        Enum(Rarity, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False)
    art_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    print_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    print_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_minted: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    compatible_hull_classes: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)

    user_cards: Mapped[list[UserCard]] = relationship(back_populates="card", lazy="selectin")


class UserCard(Base):
    __tablename__ = "user_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(20), ForeignKey("users.discord_id"), nullable=False)
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cards.id"), nullable=False
    )
    serial_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stat_modifiers: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_foil: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    races_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="user_cards")
    card: Mapped[Card] = relationship(back_populates="user_cards")


class Build(Base):
    __tablename__ = "builds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(20), ForeignKey("users.discord_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="My Ship")
    slots: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "reactor": None,
            "drive": None,
            "thrusters": None,
            "stabilizers": None,
            "hull": None,
            "overdrive": None,
            "retros": None,
        },
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hull_class: Mapped[HullClass] = mapped_column(
        Enum(HullClass, values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    core_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ship_title_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ship_titles.id", use_alter=True, name="fk_builds_ship_title_id"),
        nullable=True,
    )

    user: Mapped[User] = relationship(back_populates="builds")
    ship_title: Mapped[ShipTitle | None] = relationship(  # type: ignore[name-defined]
        "ShipTitle", foreign_keys="[Build.ship_title_id]", lazy="selectin"
    )


class Race(Base):
    __tablename__ = "races"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participants: Mapped[dict] = mapped_column(JSONB, nullable=False)
    environment: Mapped[dict] = mapped_column(JSONB, nullable=False)
    results: Mapped[dict] = mapped_column(JSONB, nullable=False)
    format: Mapped[RaceFormat] = mapped_column(
        Enum(RaceFormat, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default="sprint",
    )
    system_id: Mapped[str | None] = mapped_column(
        String(20), ForeignKey("systems.channel_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    wreck_logs: Mapped[list[WreckLog]] = relationship(back_populates="race", lazy="selectin")


class MarketListing(Base):
    __tablename__ = "market_listings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cards.id"), nullable=False
    )
    user_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_cards.id"), nullable=False
    )
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    listed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    seller: Mapped[User] = relationship(back_populates="market_listings")
    card: Mapped[Card] = relationship()
    user_card: Mapped[UserCard] = relationship()


class WreckLog(Base):
    __tablename__ = "wreck_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    race_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("races.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(20), ForeignKey("users.discord_id"), nullable=False)
    lost_parts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    race: Mapped[Race] = relationship(back_populates="wreck_logs")
    user: Mapped[User] = relationship(back_populates="wreck_logs")


class ShipRelease(Base):
    __tablename__ = "ship_releases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    serial_counter: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )

    titles: Mapped[list[ShipTitle]] = relationship(  # type: ignore[name-defined]
        "ShipTitle", back_populates="release", lazy="selectin"
    )


class ShipTitle(Base):
    __tablename__ = "ship_titles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ship_releases.id"), nullable=False
    )
    release_serial: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False
    )
    build_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("builds.id"), nullable=True
    )
    hull_class: Mapped[HullClass] = mapped_column(
        Enum(HullClass, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    race_format: Mapped[RaceFormat] = mapped_column(
        Enum(RaceFormat, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    status: Mapped[ShipStatus] = mapped_column(
        Enum(ShipStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ShipStatus.ACTIVE,
    )
    auto_name: Mapped[str] = mapped_column(String(120), nullable=False)
    custom_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    build_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pedigree_bonus: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False, server_default="0.0"
    )
    ownership_log: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    part_swap_log: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    race_record: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default='{"wins": 0, "losses": 0}'
    )
    minted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    release: Mapped[ShipRelease] = relationship(back_populates="titles")
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
