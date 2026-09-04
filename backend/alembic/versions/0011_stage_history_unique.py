"""Защита истории стадий от повторной загрузки одного перехода.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Один ранний backfill сравнил локальное время Bitrix с UTC в PostgreSQL.
    # Оставляем первую строку каждой полностью совпадающей группы.
    op.execute(
        sa.text(
            """
            DELETE FROM stage_history AS duplicate
            USING stage_history AS original
            WHERE duplicate.id > original.id
              AND duplicate.deal_id = original.deal_id
              AND duplicate.to_stage = original.to_stage
              AND duplicate.changed_at IS NOT DISTINCT FROM original.changed_at
            """
        )
    )
    op.create_unique_constraint(
        "uq_stage_history_transition",
        "stage_history",
        ["deal_id", "to_stage", "changed_at"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_stage_history_transition", "stage_history", type_="unique"
    )
