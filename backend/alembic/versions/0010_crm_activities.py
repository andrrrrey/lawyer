"""Звонки и встречи Bitrix24 для SLA и аналитики.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("crm_activities"):
        return
    op.create_table(
        "crm_activities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False, server_default=""),
        sa.Column("responsible_id", sa.String(32), nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("direction", sa.String(16), nullable=False, server_default=""),
        sa.Column("provider_id", sa.String(64), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "deal_id", "external_id", name="uq_crm_activity_deal_external"
        ),
    )
    op.create_index(
        "ix_crm_activities_occurred_at", "crm_activities", ["occurred_at"], unique=False
    )
    op.create_index(
        "ix_crm_activities_deal_kind", "crm_activities", ["deal_id", "kind"],
        unique=False,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("crm_activities"):
        op.drop_table("crm_activities")
