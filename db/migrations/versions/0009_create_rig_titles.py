"""Create rig_releases and rig_titles tables; add rig_title_id to builds

Revision ID: 0009_create_rig_titles
Revises: 0008_card_compat_body_types
Create Date: 2026-04-08
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0009_create_rig_titles"
down_revision: Union[str, None] = "0008_card_compat_body_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

car_class_enum = sa.Enum("street", "drag", "circuit", "drift", "rally", "elite", name="carclass")
rig_status_enum = sa.Enum("active", "scrapped", name="rigstatus")


def upgrade() -> None:
    op.create_table(
        "rig_releases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("serial_counter", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "rig_titles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "release_id", UUID(as_uuid=True), sa.ForeignKey("rig_releases.id"), nullable=False
        ),
        sa.Column("release_serial", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(20), sa.ForeignKey("users.discord_id"), nullable=False),
        sa.Column("build_id", UUID(as_uuid=True), sa.ForeignKey("builds.id"), nullable=True),
        sa.Column(
            "body_type",
            PgEnum(name="bodytype", create_type=False),
            nullable=False,
        ),
        sa.Column("car_class", car_class_enum, nullable=False),
        sa.Column(
            "status",
            rig_status_enum,
            nullable=False,
            server_default="active",
        ),
        sa.Column("auto_name", sa.String(120), nullable=False),
        sa.Column("custom_name", sa.String(120), nullable=True),
        sa.Column("build_snapshot", JSONB(), nullable=False),
        sa.Column("pedigree_bonus", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("ownership_log", JSONB(), nullable=False, server_default="[]"),
        sa.Column("part_swap_log", JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "race_record",
            JSONB(),
            nullable=False,
            server_default='{"wins": 0, "losses": 0}',
        ),
        sa.Column(
            "minted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Add rig_title_id to builds (use_alter to avoid circular FK at table-creation time)
    op.add_column(
        "builds",
        sa.Column("rig_title_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_builds_rig_title_id",
        "builds",
        "rig_titles",
        ["rig_title_id"],
        ["id"],
        use_alter=True,
    )

    # Seed the first release: "Season 1"
    op.execute(
        sa.text("""
            INSERT INTO rig_releases (id, name, description, started_at, serial_counter)
            VALUES (:id, :name, :description, :started_at, 0)
            """).bindparams(
            id=uuid.uuid4(),
            name="Season 1",
            description="The first season of rig titles.",
            started_at=datetime.now(timezone.utc),
        )
    )


def downgrade() -> None:
    op.drop_constraint("fk_builds_rig_title_id", "builds", type_="foreignkey")
    op.drop_column("builds", "rig_title_id")
    op.drop_table("rig_titles")
    op.drop_table("rig_releases")
    car_class_enum.drop(op.get_bind())
    rig_status_enum.drop(op.get_bind())
