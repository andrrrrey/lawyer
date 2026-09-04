"""Источник и версия построчных комментариев по сделкам.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deals",
        sa.Column("ai_comment_source", sa.String(16), nullable=False, server_default="baseline"),
    )
    op.add_column(
        "deals",
        sa.Column("ai_comment_fingerprint", sa.String(64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("deals", "ai_comment_fingerprint")
    op.drop_column("deals", "ai_comment_source")
