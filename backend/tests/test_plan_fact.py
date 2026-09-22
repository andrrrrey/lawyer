"""Расчёт месячного план-факта по компании, отделу и сотруднику."""

from __future__ import annotations

import asyncio
import pathlib
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.core.config import settings
from app.core.db import Base
from app.models import CrmActivity, Deal, OneCReceipt
from app.seeds.business import BUSINESS_SETTINGS
from app.services import business_settings, metrics, plan_fact

DB_PATH = pathlib.Path(tempfile.gettempdir()) / "lawyer_plan_fact_test.db"


def test_plan_fact_for_all_scope_levels() -> None:
    async def run() -> None:
        if DB_PATH.exists():
            DB_PATH.unlink()
        engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", poolclass=NullPool)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        previous_endpoint = settings.onec_endpoint
        settings.onec_endpoint = "https://1c.example/receipts"
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with maker() as session:
                config = deepcopy(BUSINESS_SETTINGS)
                config["departments"] = [
                    {"key": "sales", "name": "Продажи", "enabled": True}
                ]
                config["employees"] = [{
                    "key": "ivanov", "name": "Иванов", "crm_source": "box",
                    "bitrix_user_id": "12", "legal_entity_key": "uo",
                    "department_key": "sales", "enabled": True,
                }]
                config["funnels"] = [
                    {
                        "key": "box_10", "external_id": "10", "name": "Основная воронка",
                        "crm_source": "box", "legal_entity_key": "uo",
                        "sla_profile_key": "default", "entity_type": "deal", "enabled": True,
                    },
                    {
                        "key": "box_lead", "external_id": "lead", "name": "Лиды",
                        "crm_source": "box", "legal_entity_key": "uo",
                        "sla_profile_key": "default", "entity_type": "lead", "enabled": True,
                    },
                ]
                base_plan = {
                    "period": "2026-09", "legal_entity_key": "uo",
                    "funnel": "box:10", "lead_source": "Сайт",
                    "revenue": 200_000, "sales_amount": 300_000,
                    "payments": 2, "deals": 2,
                    "calls": 4, "meetings": 2,
                }
                config["plans"] = [
                    {**base_plan, "key": "company", "scope_type": "company", "scope_key": "uo"},
                    {**base_plan, "key": "department", "scope_type": "department", "scope_key": "sales"},
                    {**base_plan, "key": "employee", "scope_type": "employee", "scope_key": "ivanov"},
                ]
                await business_settings.save_settings(session, config)
                deal = Deal(
                    position=1, ref="Сделка #1", external_id="1", crm_source="box",
                    funnel_id="10", legal_entity_key="uo", name="Клиент", src="Сайт",
                    mgr="Иванов", mgr_id="12", status_label="Успех", status_class="st-ok",
                    amount=150_000, created_at=datetime(2026, 8, 25, tzinfo=UTC),
                    closed_at=datetime(2026, 9, 2, tzinfo=UTC),
                )
                session.add(deal)
                await session.flush()
                session.add(Deal(
                    position=2, ref="Лид #2", external_id="2", crm_source="box",
                    entity_type="lead", funnel_id="lead", legal_entity_key="uo",
                    name="Обращение", src="Сайт", mgr="Иванов", mgr_id="12",
                    status_label="В работе", status_class="st-mid", amount=0,
                    created_at=datetime(2026, 9, 2, tzinfo=UTC),
                ))
                # Создана в сентябре, но закрыта в октябре: в сентябрьский факт
                # успешных сделок попадать не должна.
                session.add(Deal(
                    position=4, on_dashboard=False, ref="Сделка #4", external_id="4",
                    crm_source="box",
                    funnel_id="10", legal_entity_key="uo", name="Позднее закрытие",
                    src="Сайт", mgr="Иванов", mgr_id="12", status_label="Успех",
                    status_class="st-ok", amount=900_000,
                    created_at=datetime(2026, 9, 3, tzinfo=UTC),
                    closed_at=datetime(2026, 10, 1, tzinfo=UTC),
                ))
                session.add(Deal(
                    position=3, ref="Лид #3", external_id="3", crm_source="box",
                    entity_type="lead", funnel_id="lead", legal_entity_key="uo",
                    name="Непривязанное обращение", src="Сайт", mgr="Новый сотрудник",
                    mgr_id="99", status_label="В работе", status_class="st-mid", amount=0,
                    created_at=datetime(2026, 9, 2, tzinfo=UTC),
                ))
                session.add_all([
                    CrmActivity(
                        deal_id=deal.id, external_id="c1", kind="call",
                        responsible_id="12", occurred_at=datetime(2026, 9, 3, tzinfo=UTC),
                    ),
                    CrmActivity(
                        deal_id=deal.id, external_id="c2", kind="call",
                        responsible_id="12", occurred_at=datetime(2026, 9, 4, tzinfo=UTC),
                    ),
                    CrmActivity(
                        deal_id=deal.id, external_id="m1", kind="meeting",
                        responsible_id="12", occurred_at=datetime(2026, 9, 5, tzinfo=UTC),
                    ),
                    OneCReceipt(
                        external_key="r1", legal_entity_key="uo", amount=Decimal("100000"),
                        registrar_date=datetime(2026, 9, 6, tzinfo=UTC),
                        matched_deal_id=deal.id,
                    ),
                ])
                await session.commit()

                rows = await plan_fact.rows(session, "2026-09")
                assert {row["scope_type"] for row in rows} == {
                    "company", "department", "employee"
                }
                for row in rows:
                    assert row["funnel_name"] == "Основная воронка"
                    assert row["lead_source"] == "Сайт"
                    assert row["fact"] == {
                        "revenue": 100_000.0, "sales_amount": 150_000.0,
                        "payments": 1, "deals": 1,
                        "calls": 2, "meetings": 1,
                    }
                    assert row["overall_completion"] == 50.0

                departments = await metrics.departments(session, "30")
                assert departments == [
                    {
                        "key": "sales", "name": "Продажи", "employees": 1,
                        "leads": 1, "inwork": 0, "sales": 1, "calls": 2,
                        "meetings": 1, "payments": 1, "revenue": 100_000.0,
                        "conversion": 100.0, "revenue_display": "100 000 ₽",
                    },
                    {
                        "key": "__unassigned__", "name": "Без отдела / не настроено",
                        "employees": 1, "leads": 1, "inwork": 0, "sales": 0,
                        "calls": 0, "meetings": 0, "payments": 0, "revenue": 0.0,
                        "conversion": 0.0, "revenue_display": "0 ₽",
                    },
                ]
        finally:
            settings.onec_endpoint = previous_endpoint
            await engine.dispose()
            if DB_PATH.exists():
                DB_PATH.unlink()

    asyncio.run(run())
