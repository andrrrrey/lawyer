"""Фактическая дата завершения сделки Bitrix24.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("deals")}
    if "closed_at" not in columns:
        op.add_column(
            "deals", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("deals")}
    if "closed_at" in columns:
        op.drop_column("deals", "closed_at")
