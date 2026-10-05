"""Индексы для быстрых витрин дашборда и журнала 1С.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_deals_dashboard_created", "deals", ["on_dashboard", "created_at"])
    op.create_index(
        "ix_deals_dashboard_status_closed",
        "deals",
        ["on_dashboard", "status_class", "closed_at"],
    )
    op.create_index("ix_deals_legal_entity", "deals", ["legal_entity_key"])
    op.create_index("ix_deals_manager", "deals", ["mgr"])
    op.create_index("ix_deals_source", "deals", ["src"])
    op.create_index("ix_deals_funnel", "deals", ["crm_source", "funnel_id"])
    op.create_index("ix_stage_history_deal", "stage_history", ["deal_id"])
    op.create_index("ix_crm_activities_deal_date", "crm_activities", ["deal_id", "occurred_at"])
    op.create_index(
        "ix_one_c_receipts_date_excluded",
        "one_c_receipts",
        ["registrar_date", "excluded"],
    )
    op.create_index("ix_one_c_receipts_matched", "one_c_receipts", ["matched_deal_id"])


def downgrade() -> None:
    op.drop_index("ix_one_c_receipts_matched", table_name="one_c_receipts")
    op.drop_index("ix_one_c_receipts_date_excluded", table_name="one_c_receipts")
    op.drop_index("ix_crm_activities_deal_date", table_name="crm_activities")
    op.drop_index("ix_stage_history_deal", table_name="stage_history")
    op.drop_index("ix_deals_funnel", table_name="deals")
    op.drop_index("ix_deals_source", table_name="deals")
    op.drop_index("ix_deals_manager", table_name="deals")
    op.drop_index("ix_deals_legal_entity", table_name="deals")
    op.drop_index("ix_deals_dashboard_status_closed", table_name="deals")
    op.drop_index("ix_deals_dashboard_created", table_name="deals")
