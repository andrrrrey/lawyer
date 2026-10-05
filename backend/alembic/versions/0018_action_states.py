"""Persist review and ROMI actions.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("budget_recs", sa.Column("status", sa.String(16), nullable=False, server_default="new"))
    op.add_column("budget_recs", sa.Column("legal_entity_key", sa.String(32), nullable=False, server_default=""))
    op.add_column("budget_recs", sa.Column("deferred_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("budget_recs", sa.Column("acted_by", sa.String(128), nullable=True))
    op.add_column("budget_recs", sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_key", sa.String(160), nullable=False),
        sa.Column("ptype", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="justified"),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("decided_by", sa.String(128), nullable=False, server_default=""),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("deal_key", "ptype", name="uq_review_decision_deal_type"),
    )
    op.add_column("minus_words", sa.Column("legal_entity_key", sa.String(32), nullable=False, server_default=""))
    op.add_column("minus_words", sa.Column("date_from", sa.Date(), nullable=True))
    op.add_column("minus_words", sa.Column("date_to", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_table("review_decisions")
    op.drop_column("minus_words", "date_to")
    op.drop_column("minus_words", "date_from")
    op.drop_column("minus_words", "legal_entity_key")
    op.drop_column("budget_recs", "acted_at")
    op.drop_column("budget_recs", "acted_by")
    op.drop_column("budget_recs", "deferred_until")
    op.drop_column("budget_recs", "status")
    op.drop_column("budget_recs", "legal_entity_key")
