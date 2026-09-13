"""Точечная догрузка сделок Bitrix24 по ссылкам из заказов 1С."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.db import Base
from app.models import Deal
from app.services import onec_sync


class FakeBitrix:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def fetch_deals_by_ids(self, deal_ids: list[str], extra_fields=None) -> list[dict]:  # noqa: ANN001, ARG002
        self.requested.extend(deal_ids)
        return [{
            "external_id": item,
            "ref": f"Сделка #{item}",
            "name": f"Старая сделка {item}",
            "funnel_id": "7",
            "stage": "WON",
            "semantic": "S",
            "mgr": "12",
            "src": "WEB",
            "amount": 1000,
            "created": "2025-01-01T00:00:00+03:00",
            "crm_source": "cloud",
        } for item in deal_ids]

    def fetch_users(self) -> list[dict]:
        return [{"id": "12", "name": "Иван Иванов"}]

    def fetch_stages(self) -> list[dict]:
        return [{"id": "WON", "name": "Успешно"}]

    def fetch_sources(self) -> list[dict]:
        return [{"id": "WEB", "name": "Сайт"}]

    def fetch_contact_phones(self, contact_ids: list[str]) -> dict[str, str]:  # noqa: ARG002
        return {}


def test_backfill_fetches_only_missing_deal_from_configured_portal(monkeypatch) -> None:
    async def run() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite://", poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        adapter = FakeBitrix()
        monkeypatch.setattr(
            onec_sync.factory,
            "get_bitrix24_connections",
            lambda: [("cloud", adapter)],
        )
        config = {
            "funnels": [{
                "crm_source": "cloud", "entity_type": "deal", "external_id": "7",
                "legal_entity_key": "urpase", "name": "Экспертиза", "enabled": True,
                "expected_payment_stages": [],
            }],
            "employees": [],
        }
        receipts = [{
            "crm_external_id": "991", "crm_entity_type": "deal",
            "legal_entity_key": "urpase", "excluded": False,
        }]
        async with maker() as session:
            result = await onec_sync._backfill_missing_deals(
                session, receipts, config, deals=[]
            )
            rows = list((await session.scalars(select(Deal))).all())
            assert result["requested"] == 1
            assert result["created"] == 1
            assert adapter.requested == ["991"]
            assert len(rows) == 1
            assert rows[0].external_id == "991"
            assert rows[0].crm_source == "cloud"
            assert rows[0].legal_entity_key == "urpase"
            assert rows[0].mgr == "Иван Иванов"
        await engine.dispose()

    asyncio.run(run())
