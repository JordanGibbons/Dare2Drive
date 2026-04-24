"""initial salvage-pulp schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-23 03:13:27.735599
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Tables with no FKs first ──────────────────────────────────────────────
    op.create_table(
        "sectors",
        sa.Column("guild_id", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("flavor_text", sa.String(length=500), nullable=True),
        sa.Column("system_cap", sa.Integer(), server_default="1", nullable=False),
        sa.Column("owner_discord_id", sa.String(length=20), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("guild_id"),
    )

    op.create_table(
        "users",
        sa.Column("discord_id", sa.String(length=20), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column(
            "hull_class",
            sa.Enum("hauler", "skirmisher", "scout", name="hullclass"),
            nullable=False,
        ),
        sa.Column("currency", sa.Integer(), nullable=False),
        sa.Column("xp", sa.Integer(), nullable=False),
        sa.Column(
            "tutorial_step",
            sa.Enum(
                "started",
                "inventory",
                "inspect",
                "equip",
                "mint",
                "garage",
                "race",
                "pack",
                "complete",
                name="tutorialstep",
            ),
            nullable=False,
        ),
        sa.Column("last_daily", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("discord_id"),
    )

    op.create_table(
        "cards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "slot",
            sa.Enum(
                "reactor",
                "drive",
                "thrusters",
                "stabilizers",
                "hull",
                "overdrive",
                "retros",
                name="cardslot",
            ),
            nullable=False,
        ),
        sa.Column(
            "rarity",
            sa.Enum(
                "common",
                "uncommon",
                "rare",
                "epic",
                "legendary",
                "ghost",
                name="rarity",
            ),
            nullable=False,
        ),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("art_path", sa.String(length=255), nullable=True),
        sa.Column("print_number", sa.Integer(), nullable=True),
        sa.Column("print_max", sa.Integer(), nullable=True),
        sa.Column("total_minted", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "compatible_hull_classes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "ship_releases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("serial_counter", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Tables with FKs to the above ──────────────────────────────────────────
    op.create_table(
        "systems",
        sa.Column("channel_id", sa.String(length=20), nullable=False),
        sa.Column("sector_id", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("flavor_text", sa.String(length=500), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "enabled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["sector_id"], ["sectors.guild_id"]),
        sa.PrimaryKeyConstraint("channel_id"),
    )

    # builds created without ship_title_id FK (cycle broken — ALTER at end)
    op.create_table(
        "builds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slots", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "hull_class",
            sa.Enum("hauler", "skirmisher", "scout", name="hullclass"),
            nullable=True,
        ),
        sa.Column("core_locked", sa.Boolean(), nullable=False),
        sa.Column("ship_title_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ship_titles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("release_id", sa.UUID(), nullable=False),
        sa.Column("release_serial", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(length=20), nullable=False),
        sa.Column("build_id", sa.UUID(), nullable=True),
        sa.Column(
            "hull_class",
            sa.Enum("hauler", "skirmisher", "scout", name="hullclass"),
            nullable=False,
        ),
        sa.Column(
            "race_format",
            sa.Enum("sprint", "endurance", "gauntlet", name="raceformat"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("active", "scrapped", name="shipstatus"),
            nullable=False,
        ),
        sa.Column("auto_name", sa.String(length=120), nullable=False),
        sa.Column("custom_name", sa.String(length=120), nullable=True),
        sa.Column(
            "build_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("pedigree_bonus", sa.Float(), server_default="0.0", nullable=False),
        sa.Column(
            "ownership_log",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "part_swap_log",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "race_record",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{"wins": 0, "losses": 0}',
            nullable=False,
        ),
        sa.Column(
            "minted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["build_id"], ["builds.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.discord_id"]),
        sa.ForeignKeyConstraint(["release_id"], ["ship_releases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_cards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=20), nullable=False),
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("serial_number", sa.Integer(), nullable=False),
        sa.Column(
            "stat_modifiers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("is_foil", sa.Boolean(), nullable=False),
        sa.Column("races_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "acquired_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "market_listings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("seller_id", sa.String(length=20), nullable=False),
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("user_card_id", sa.UUID(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column(
            "listed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"]),
        sa.ForeignKeyConstraint(["seller_id"], ["users.discord_id"]),
        sa.ForeignKeyConstraint(["user_card_id"], ["user_cards.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "races",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("participants", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("environment", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "format",
            sa.Enum("sprint", "endurance", "gauntlet", name="raceformat"),
            server_default="sprint",
            nullable=False,
        ),
        sa.Column("system_id", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["system_id"], ["systems.channel_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "wreck_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("race_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(length=20), nullable=False),
        sa.Column("lost_parts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["race_id"], ["races.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.discord_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Complete the circular FK builds ↔ ship_titles ─────────────────────────
    op.create_foreign_key(
        "fk_builds_ship_title_id",
        "builds",
        "ship_titles",
        ["ship_title_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_builds_ship_title_id", "builds", type_="foreignkey")
    op.drop_table("wreck_logs")
    op.drop_table("races")
    op.drop_table("market_listings")
    op.drop_table("user_cards")
    op.drop_table("ship_titles")
    op.drop_table("builds")
    op.drop_table("systems")
    op.drop_table("ship_releases")
    op.drop_table("cards")
    op.drop_table("users")
    op.drop_table("sectors")
    # Drop enum types created above.
    sa.Enum(name="cardslot").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="raceformat").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="shipstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tutorialstep").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="hullclass").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="rarity").drop(op.get_bind(), checkfirst=True)
