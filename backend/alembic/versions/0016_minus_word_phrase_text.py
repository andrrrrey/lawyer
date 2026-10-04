"""Поисковые фразы Яндекс Директа без ограничения длины.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "minus_words",
        "phrase",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "minus_words",
        "phrase",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=False,
        postgresql_using="left(phrase, 255)",
    )
