"""SQLAlchemy async models for Dare2Drive."""

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


class BodyType(str, enum.Enum):
    MUSCLE = "muscle"
    SPORT = "sport"
    COMPACT = "compact"


class CarClass(str, enum.Enum):
    STREET = "street"
    DRAG = "drag"
    CIRCUIT = "circuit"
    DRIFT = "drift"
    RALLY = "rally"
    ELITE = "elite"


class RigStatus(str, enum.Enum):
    ACTIVE = "active"
    SCRAPPED = "scrapped"


class TutorialStep(str, enum.Enum):
    """Tracks player progress through the onboarding tutorial."""

    STARTED = "started"  # Just picked body type, story playing
    INVENTORY = "inventory"  # Told to use /inventory
    INSPECT = "inspect"  # Told to use /inspect
    EQUIP = "equip"  # Told to use /equip
    MINT = "mint"  # All 7 slots filled — learn /build preview + /build mint
    GARAGE = "garage"  # Told to check /garage
    RACE = "race"  # Told to /race the NPC
    PACK = "pack"  # Won/lost, opening reward pack
    COMPLETE = "complete"  # Tutorial done, all commands unlocked


class CardSlot(str, enum.Enum):
    ENGINE = "engine"
    TRANSMISSION = "transmission"
    TIRES = "tires"
    SUSPENSION = "suspension"
    CHASSIS = "chassis"
    TURBO = "turbo"
    BRAKES = "brakes"


class Rarity(str, enum.Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"
    GHOST = "ghost"


# ──────────── Models ────────────


class User(Base):
    __tablename__ = "users"

    discord_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    body_type: Mapped[BodyType] = mapped_column(
        Enum(BodyType, values_callable=lambda x: [e.value for e in x]), nullable=False
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

    # relationships
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
    compatible_body_types: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)

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
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="My Build")
    slots: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "engine": None,
            "transmission": None,
            "tires": None,
            "suspension": None,
            "chassis": None,
            "turbo": None,
            "brakes": None,
        },
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    body_type: Mapped[BodyType] = mapped_column(
        Enum(BodyType, values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    core_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rig_title_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rig_titles.id"), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="builds")
    rig_title: Mapped[RigTitle | None] = relationship(  # type: ignore[name-defined]
        "RigTitle", foreign_keys="[Build.rig_title_id]", lazy="selectin"
    )


class Race(Base):
    __tablename__ = "races"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    participants: Mapped[dict] = mapped_column(JSONB, nullable=False)
    environment: Mapped[dict] = mapped_column(JSONB, nullable=False)
    results: Mapped[dict] = mapped_column(JSONB, nullable=False)
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


class RigRelease(Base):
    __tablename__ = "rig_releases"

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

    titles: Mapped[list[RigTitle]] = relationship(  # type: ignore[name-defined]
        "RigTitle", back_populates="release", lazy="selectin"
    )


class RigTitle(Base):
    __tablename__ = "rig_titles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rig_releases.id"), nullable=False
    )
    release_serial: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False
    )
    build_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("builds.id"), nullable=True
    )
    body_type: Mapped[BodyType] = mapped_column(
        Enum(BodyType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    car_class: Mapped[CarClass] = mapped_column(
        Enum(CarClass, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    status: Mapped[RigStatus] = mapped_column(
        Enum(RigStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=RigStatus.ACTIVE,
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

    release: Mapped[RigRelease] = relationship(back_populates="titles")
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
