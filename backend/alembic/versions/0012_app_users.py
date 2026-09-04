"""Пользователи и роли дашборда.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("login", sa.String(128), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="manager"),
        sa.Column("employee_key", sa.String(128), nullable=False, server_default=""),
        sa.Column("department_key", sa.String(128), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_users_login", "app_users", ["login"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_app_users_login", table_name="app_users")
    op.drop_table("app_users")
