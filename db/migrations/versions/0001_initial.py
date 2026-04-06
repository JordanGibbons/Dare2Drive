"""Initial schema — all tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum types — created explicitly; create_type=False suppresses auto-creation inside create_table
bodytype_enum = postgresql.ENUM("muscle", "sport", "compact", name="bodytype", create_type=False)
cardslot_enum = postgresql.ENUM(
    "engine",
    "transmission",
    "tires",
    "suspension",
    "chassis",
    "turbo",
    "brakes",
    name="cardslot",
    create_type=False,
)
rarity_enum = postgresql.ENUM(
    "common",
    "uncommon",
    "rare",
    "epic",
    "legendary",
    "ghost",
    name="rarity",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    # Create enum types (idempotent)
    postgresql.ENUM("muscle", "sport", "compact", name="bodytype").create(bind, checkfirst=True)
    postgresql.ENUM(
        "engine",
        "transmission",
        "tires",
        "suspension",
        "chassis",
        "turbo",
        "brakes",
        name="cardslot",
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "common",
        "uncommon",
        "rare",
        "epic",
        "legendary",
        "ghost",
        name="rarity",
    ).create(bind, checkfirst=True)

    # Users
    op.create_table(
        "users",
        sa.Column("discord_id", sa.String(20), primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("body_type", bodytype_enum, nullable=False),
        sa.Column("currency", sa.Integer, nullable=False, server_default="500"),
        sa.Column("xp", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Cards
    op.create_table(
        "cards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("slot", cardslot_enum, nullable=False),
        sa.Column("rarity", rarity_enum, nullable=False),
        sa.Column("stats", postgresql.JSONB, nullable=False),
        sa.Column("art_path", sa.String(255), nullable=True),
        sa.Column("print_number", sa.Integer, nullable=True),
        sa.Column("print_max", sa.Integer, nullable=True),
    )

    # User Cards
    op.create_table(
        "user_cards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(20), sa.ForeignKey("users.discord_id"), nullable=False),
        sa.Column(
            "card_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cards.id"), nullable=False
        ),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_foil", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "acquired_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Builds
    op.create_table(
        "builds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(20), sa.ForeignKey("users.discord_id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False, server_default="'My Build'"),
        sa.Column("slots", postgresql.JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )

    # Races
    op.create_table(
        "races",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("participants", postgresql.JSONB, nullable=False),
        sa.Column("environment", postgresql.JSONB, nullable=False),
        sa.Column("results", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Market Listings
    op.create_table(
        "market_listings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("seller_id", sa.String(20), sa.ForeignKey("users.discord_id"), nullable=False),
        sa.Column(
            "card_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cards.id"), nullable=False
        ),
        sa.Column("price", sa.Integer, nullable=False),
        sa.Column(
            "listed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Wreck Logs
    op.create_table(
        "wreck_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "race_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("races.id"), nullable=False
        ),
        sa.Column("user_id", sa.String(20), sa.ForeignKey("users.discord_id"), nullable=False),
        sa.Column("lost_parts", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("wreck_logs")
    op.drop_table("market_listings")
    op.drop_table("races")
    op.drop_table("builds")
    op.drop_table("user_cards")
    op.drop_table("cards")
    op.drop_table("users")
    bind = op.get_bind()
    postgresql.ENUM(name="rarity").drop(bind, checkfirst=True)
    postgresql.ENUM(name="cardslot").drop(bind, checkfirst=True)
    postgresql.ENUM(name="bodytype").drop(bind, checkfirst=True)
