"""SQLAlchemy async models for Dare2Drive."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
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
    body_type: Mapped[BodyType] = mapped_column(Enum(BodyType, values_callable=lambda x: [e.value for e in x]), nullable=False)
    currency: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
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

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    slot: Mapped[CardSlot] = mapped_column(Enum(CardSlot, values_callable=lambda x: [e.value for e in x]), nullable=False)
    rarity: Mapped[Rarity] = mapped_column(Enum(Rarity, values_callable=lambda x: [e.value for e in x]), nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False)
    art_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    print_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    print_max: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user_cards: Mapped[list[UserCard]] = relationship(back_populates="card", lazy="selectin")


class UserCard(Base):
    __tablename__ = "user_cards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cards.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_foil: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="user_cards")
    card: Mapped[Card] = relationship(back_populates="user_cards")


class Build(Base):
    __tablename__ = "builds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False
    )
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

    user: Mapped[User] = relationship(back_populates="builds")


class Race(Base):
    __tablename__ = "races"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    participants: Mapped[dict] = mapped_column(JSONB, nullable=False)
    environment: Mapped[dict] = mapped_column(JSONB, nullable=False)
    results: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    wreck_logs: Mapped[list[WreckLog]] = relationship(back_populates="race", lazy="selectin")


class MarketListing(Base):
    __tablename__ = "market_listings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    seller_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cards.id"), nullable=False
    )
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    listed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    seller: Mapped[User] = relationship(back_populates="market_listings")
    card: Mapped[Card] = relationship()


class WreckLog(Base):
    __tablename__ = "wreck_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    race_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("races.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False
    )
    lost_parts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    race: Mapped[Race] = relationship(back_populates="wreck_logs")
    user: Mapped[User] = relationship(back_populates="wreck_logs")
