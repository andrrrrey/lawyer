"""Ручной журнал управленческих расходов.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("manual_expenses"):
        return
    op.create_table(
        "manual_expenses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("spent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("legal_entity_key", sa.String(32), nullable=False, server_default=""),
        sa.Column("article", sa.String(128), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("include_in_romi", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("channel", sa.String(128), nullable=False, server_default=""),
        sa.Column("campaign", sa.String(128), nullable=False, server_default=""),
        sa.Column("comment", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_manual_expenses_spent_at", "manual_expenses", ["spent_at"], unique=False
    )
    op.create_index(
        "ix_manual_expenses_legal_entity", "manual_expenses", ["legal_entity_key"],
        unique=False,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("manual_expenses"):
        op.drop_table("manual_expenses")
