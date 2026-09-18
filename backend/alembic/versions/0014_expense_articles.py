"""Справочник статей расходов.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("expense_articles"):
        return
    op.create_table(
        "expense_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("legal_entity_key", sa.String(32), nullable=False, server_default=""),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "legal_entity_key", "name", name="uq_expense_article_entity_name"
        ),
    )
    op.create_index(
        "ix_expense_articles_entity", "expense_articles", ["legal_entity_key"],
        unique=False,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("expense_articles"):
        op.drop_table("expense_articles")
