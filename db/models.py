"""SQLAlchemy async models for Dare2Drive (Salvage-Pulp universe)."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,  # noqa: F401 – reserved for Phase 2a numeric columns
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
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


class CrewArchetype(str, enum.Enum):
    PILOT = "pilot"
    ENGINEER = "engineer"
    GUNNER = "gunner"
    NAVIGATOR = "navigator"
    MEDIC = "medic"


class JobType(str, enum.Enum):
    TIMER_COMPLETE = "timer_complete"
    ACCRUAL_TICK = "accrual_tick"
    EXPEDITION_EVENT = "expedition_event"
    EXPEDITION_AUTO_RESOLVE = "expedition_auto_resolve"
    EXPEDITION_RESOLVE = "expedition_resolve"
    EXPEDITION_COMPLETE = "expedition_complete"


class JobState(str, enum.Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TimerType(str, enum.Enum):
    TRAINING = "training"
    RESEARCH = "research"
    SHIP_BUILD = "ship_build"


class TimerState(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StationType(str, enum.Enum):
    CARGO_RUN = "cargo_run"
    REPAIR_BAY = "repair_bay"
    WATCH_TOWER = "watch_tower"


class RewardSourceType(str, enum.Enum):
    TIMER_COMPLETE = "timer_complete"
    ACCRUAL_TICK = "accrual_tick"
    ACCRUAL_CLAIM = "accrual_claim"
    TIMER_CANCEL_REFUND = "timer_cancel_refund"
    EXPEDITION_OUTCOME = "expedition_outcome"


class CrewActivity(str, enum.Enum):
    IDLE = "idle"
    ON_BUILD = "on_build"
    TRAINING = "training"
    RESEARCHING = "researching"
    ON_STATION = "on_station"
    ON_EXPEDITION = "on_expedition"


class ExpeditionState(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class BuildActivity(str, enum.Enum):
    IDLE = "idle"
    ON_EXPEDITION = "on_expedition"


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
    # server_default literal is frozen by migration 0003_phase2a_scheduler;
    # any change to the JSON requires a new migration that updates existing rows.
    notification_prefs: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"timer_completion": "dm", "accrual_threshold": "dm", "_version": 1}',
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


class CrewMember(Base):
    __tablename__ = "crew_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False, index=True
    )
    first_name: Mapped[str] = mapped_column(String(60), nullable=False)
    last_name: Mapped[str] = mapped_column(String(60), nullable=False)
    callsign: Mapped[str] = mapped_column(String(60), nullable=False)
    archetype: Mapped[CrewArchetype] = mapped_column(
        Enum(CrewArchetype, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    rarity: Mapped[Rarity] = mapped_column(
        Enum(Rarity, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    portrait_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_activity: Mapped[CrewActivity] = mapped_column(
        Enum(CrewActivity, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default="idle",
    )
    current_activity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "first_name",
            "last_name",
            "callsign",
            name="uq_crew_members_user_name",
        ),
        Index("ix_crew_members_user_archetype", "user_id", "archetype"),
    )


class CrewAssignment(Base):
    __tablename__ = "crew_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crew_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crew_members.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    build_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("builds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    archetype: Mapped[CrewArchetype] = mapped_column(
        Enum(CrewArchetype, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("build_id", "archetype", name="uq_crew_assignments_build_archetype"),
    )


class CrewDailyLead(Base):
    __tablename__ = "crew_daily_leads"

    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), primary_key=True
    )
    rolled_for_date: Mapped[date] = mapped_column(Date, primary_key=True)
    archetype: Mapped[CrewArchetype] = mapped_column(
        Enum(CrewArchetype, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    rarity: Mapped[Rarity] = mapped_column(
        Enum(Rarity, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(60), nullable=False)
    last_name: Mapped[str] = mapped_column(String(60), nullable=False)
    callsign: Mapped[str] = mapped_column(String(60), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ──────────── Phase 2a: Scheduler / Timers / Accrual ────────────


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False, index=True
    )
    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default="pending",
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_scheduled_jobs_pending_due",
            "state",
            "scheduled_for",
            postgresql_where="state IN ('pending', 'claimed')",
        ),
    )


class Timer(Base):
    __tablename__ = "timers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False, index=True
    )
    timer_type: Mapped[TimerType] = mapped_column(
        Enum(TimerType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    recipe_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[TimerState] = mapped_column(
        Enum(TimerState, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default="active",
    )
    linked_scheduled_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scheduled_jobs.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ux_timers_one_research_active",
            "user_id",
            unique=True,
            postgresql_where="timer_type = 'research' AND state = 'active'",
        ),
        Index(
            "ux_timers_one_ship_build_active",
            "user_id",
            unique=True,
            postgresql_where="timer_type = 'ship_build' AND state = 'active'",
        ),
    )


class StationAssignment(Base):
    __tablename__ = "station_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False, index=True
    )
    station_type: Mapped[StationType] = mapped_column(
        Enum(StationType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    crew_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crew_members.id"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_yield_tick_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    pending_credits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    pending_xp: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    recalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ux_station_assignments_user_type_active",
            "user_id",
            "station_type",
            unique=True,
            postgresql_where="recalled_at IS NULL",
        ),
    )


class RewardLedger(Base):
    __tablename__ = "reward_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("users.discord_id"), nullable=False, index=True
    )
    source_type: Mapped[RewardSourceType] = mapped_column(
        Enum(RewardSourceType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    delta: Mapped[dict] = mapped_column(JSONB, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("source_type", "source_id", name="ux_reward_ledger_source"),)
