"""Allow heads to see whole legal entities.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_users",
        sa.Column("scope_mode", sa.String(24), nullable=False, server_default="department"),
    )
    op.add_column(
        "app_users",
        sa.Column(
            "legal_entity_keys", sa.JSON(), nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_users", "legal_entity_keys")
    op.drop_column("app_users", "scope_mode")
