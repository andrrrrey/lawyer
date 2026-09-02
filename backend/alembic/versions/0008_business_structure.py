"""Три юрлица, два источника CRM и фактические поступления 1С.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return inspector.has_table(table) and any(
        item["name"] == column for item in inspector.get_columns(table)
    )


def _add_column(table: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_column(inspector, table, column.name):
        op.add_column(table, column)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("business_settings"):
        op.create_table(
            "business_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    _add_column(
        "deals",
        sa.Column("crm_source", sa.String(32), nullable=False, server_default="primary"),
    )
    _add_column(
        "deals",
        sa.Column("entity_type", sa.String(16), nullable=False, server_default="deal"),
    )
    _add_column(
        "deals",
        sa.Column("legal_entity_key", sa.String(32), nullable=False, server_default=""),
    )
    _add_column(
        "deals",
        sa.Column("funnel_id", sa.String(48), nullable=False, server_default=""),
    )
    _add_column(
        "deals",
        sa.Column("funnel_name", sa.String(128), nullable=False, server_default=""),
    )

    inspector = sa.inspect(op.get_bind())
    deal_indexes = {index["name"] for index in inspector.get_indexes("deals")}
    if "uq_deal_crm_identity" not in deal_indexes:
        op.create_index(
            "uq_deal_crm_identity",
            "deals",
            ["crm_source", "entity_type", "external_id"],
            unique=True,
        )

    _add_column(
        "ad_costs",
        sa.Column("legal_entity_key", sa.String(32), nullable=False, server_default=""),
    )
    _add_column(
        "ad_costs",
        sa.Column("account_key", sa.String(48), nullable=False, server_default=""),
    )
    _add_column(
        "visits",
        sa.Column("legal_entity_key", sa.String(32), nullable=False, server_default=""),
    )
    _add_column(
        "visits",
        sa.Column("account_key", sa.String(48), nullable=False, server_default=""),
    )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("one_c_receipts"):
        op.create_table(
            "one_c_receipts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("external_key", sa.String(72), nullable=False),
            sa.Column("registrar_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("registrar_number", sa.String(64), nullable=False, server_default=""),
            sa.Column("registrar_type", sa.String(64), nullable=False, server_default=""),
            sa.Column("registrar_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("legal_entity_key", sa.String(32), nullable=False, server_default=""),
            sa.Column("organization_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("organization_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("organization_inn", sa.String(16), nullable=False, server_default=""),
            sa.Column("counterparty_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("counterparty_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("counterparty_inn", sa.String(16), nullable=False, server_default=""),
            sa.Column("contract_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("contract_number", sa.String(128), nullable=False, server_default=""),
            sa.Column("article_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("article_code", sa.String(128), nullable=False, server_default=""),
            sa.Column("article_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("operation", sa.String(16), nullable=False, server_default="income"),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(8), nullable=False, server_default="RUB"),
            sa.Column("crm_source", sa.String(32), nullable=False, server_default=""),
            sa.Column("crm_entity_type", sa.String(16), nullable=False, server_default=""),
            sa.Column("crm_external_id", sa.String(48), nullable=False, server_default=""),
            sa.Column("matched_deal_id", sa.Integer(), nullable=True),
            sa.Column("excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("exclusion_reason", sa.String(255), nullable=False, server_default=""),
            sa.Column("raw", sa.JSON(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["matched_deal_id"], ["deals.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("external_key"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("one_c_receipts"):
        op.drop_table("one_c_receipts")
    if inspector.has_table("visits"):
        for column in ("account_key", "legal_entity_key"):
            if _has_column(sa.inspect(op.get_bind()), "visits", column):
                op.drop_column("visits", column)
    if inspector.has_table("ad_costs"):
        for column in ("account_key", "legal_entity_key"):
            if _has_column(sa.inspect(op.get_bind()), "ad_costs", column):
                op.drop_column("ad_costs", column)
    if inspector.has_table("deals"):
        index_names = {index["name"] for index in inspector.get_indexes("deals")}
        if "uq_deal_crm_identity" in index_names:
            op.drop_index("uq_deal_crm_identity", table_name="deals")
        for column in (
            "funnel_name",
            "funnel_id",
            "legal_entity_key",
            "entity_type",
            "crm_source",
        ):
            if _has_column(sa.inspect(op.get_bind()), "deals", column):
                op.drop_column("deals", column)
    if inspector.has_table("business_settings"):
        op.drop_table("business_settings")
