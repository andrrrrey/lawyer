"""Быстрая сверка сделок с Битрикс24 (событие портала и тик планировщика).

Ключевое требование: сверка обновляет строки сделок на месте. Пересоздание
сносило бы каскадом локально поставленные задачи, и «сделки без задач»
возвращались бы в мониторинг через несколько минут после постановки задачи.
"""

from __future__ import annotations

import asyncio
import pathlib
import tempfile
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 — регистрирует таблицы
from app.core.config import settings
from app.core.db import Base
from app.integrations import factory
from app.models import Deal, Task
from app.services import ingest

DB_PATH = pathlib.Path(tempfile.gettempdir()) / "lawyer_sync_test.db"


def _raw(deal_id: str, *, title: str, stage: str = "NEW", mgr: str = "12",
         amount: int = 0, semantic: str = "P") -> dict:
    """Нормализованная запись сделки в форме, которую отдаёт адаптер Битрикс24."""
    return {
        "external_id": deal_id, "ref": f"Сделка #{deal_id}", "name": title,
        "stage": stage, "semantic": semantic, "mgr": mgr, "contact_id": None,
        "src": "site", "utm": None, "campaign": None, "amount": amount,
        "created": "2026-08-01T10:00:00+03:00",
        "last_activity": "2026-08-18T10:00:00+03:00", "custom": {},
    }


class FakeBitrix:
    """Адаптер-заглушка: отдаёт заданный набор сделок и справочники портала."""

    def __init__(self, deals: list[dict]) -> None:
        self.deals = deals
        self.last_call: dict[str, Any] = {}

    def fetch_deals(self, created_after=None, extra_fields=None, modified_after=None):
        self.last_call = {"created_after": created_after, "modified_after": modified_after}
        return [dict(d) for d in self.deals]

    def fetch_users(self):
        return [{"id": "12", "name": "Михаил Иванов"}]

    def fetch_stages(self):
        return [{"id": "NEW", "name": "Новое обращение"}, {"id": "WON", "name": "Оплачено"}]

    def fetch_sources(self):
        return [{"id": "site", "name": "Сайт"}]

    def fetch_contact_phones(self, contact_ids):  # noqa: ARG002
        return {}


def with_db(check: Callable[[AsyncSession], Coroutine[Any, Any, None]]) -> None:
    """Прогоняет проверку на отдельной БД в боевом режиме."""
    async def run() -> None:
        if DB_PATH.exists():
            DB_PATH.unlink()
        engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", poolclass=NullPool)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        prev_source, prev_hook = settings.data_source, settings.bitrix24_webhook_url
        settings.data_source = "real"
        settings.bitrix24_webhook_url = "https://portal.example/rest/1/token/"
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with maker() as session:
                await check(session)
        finally:
            settings.data_source = prev_source
            settings.bitrix24_webhook_url = prev_hook
            await engine.dispose()
            if DB_PATH.exists():
                DB_PATH.unlink()

    asyncio.run(run())


def test_sync_keeps_local_tasks(monkeypatch) -> None:
    """Обновление сделки не сносит поставленную по ней задачу."""
    async def check(s: AsyncSession) -> None:
        portal = FakeBitrix([_raw("100", title="ООО «ТеплоДом»")])
        monkeypatch.setattr(factory, "get_bitrix24", lambda: portal)

        await ingest.refresh_deals(s)
        deal = (await s.execute(select(Deal))).scalar_one()
        deal_id = deal.id
        s.add(Task(deal_id=deal_id, title="Связаться с клиентом", assignee="Михаил Иванов"))
        await s.commit()

        # Сделку изменили в портале — прилетело событие, идёт сверка.
        portal.deals = [_raw("100", title="ООО «ТеплоДом»", stage="WON", amount=145_000)]
        result = await ingest.refresh_deals(s)

        assert result == {
            "skipped": False, "created": 0, "updated": 1, "removed": 0, "full": False,
        }
        deal = (await s.execute(select(Deal))).scalar_one()
        assert deal.id == deal_id           # строка обновлена, а не пересоздана
        assert deal.amount == 145_000       # новые данные приехали
        assert deal.status_class == "st-ok"
        # Задача на месте — иначе «сделка без задачи» вернулась бы в мониторинг.
        assert (await s.execute(select(Task))).scalars().all()

    with_db(check)


def test_sync_resolves_dictionaries(monkeypatch) -> None:
    """Стадия, ответственный и источник приезжают названиями, а не кодами."""
    async def check(s: AsyncSession) -> None:
        monkeypatch.setattr(
            factory, "get_bitrix24", lambda: FakeBitrix([_raw("100", title="Сделка")]))
        await ingest.refresh_deals(s)

        deal = (await s.execute(select(Deal))).scalar_one()
        assert deal.stage == "Новое обращение"
        assert deal.mgr == "Михаил Иванов"
        assert deal.mgr_id == "12"
        assert deal.src == "Сайт"

    with_db(check)


def test_sync_adds_new_deals(monkeypatch) -> None:
    """Новая сделка портала появляется, существующие не дублируются."""
    async def check(s: AsyncSession) -> None:
        portal = FakeBitrix([_raw("100", title="Первая")])
        monkeypatch.setattr(factory, "get_bitrix24", lambda: portal)
        await ingest.refresh_deals(s)

        portal.deals = [_raw("100", title="Первая"), _raw("101", title="Вторая")]
        result = await ingest.refresh_deals(s)

        assert (result["created"], result["updated"]) == (1, 1)
        refs = {d.external_id for d in (await s.execute(select(Deal))).scalars().all()}
        assert refs == {"100", "101"}

    with_db(check)


def test_quick_sync_keeps_deals_outside_the_batch(monkeypatch) -> None:
    """Частая сверка тянет только изменённые сделки и не трогает остальные."""
    async def check(s: AsyncSession) -> None:
        portal = FakeBitrix([_raw("100", title="Первая"), _raw("101", title="Вторая")])
        monkeypatch.setattr(factory, "get_bitrix24", lambda: portal)
        await ingest.refresh_deals(s, full=True)

        # В выборку изменённых попала одна сделка — вторая должна остаться в БД.
        portal.deals = [_raw("101", title="Вторая · обновлена")]
        result = await ingest.refresh_deals(s)

        assert result["removed"] == 0
        assert portal.last_call["modified_after"] and not portal.last_call["created_after"]
        names = {d.external_id: d.name for d in (await s.execute(select(Deal))).scalars().all()}
        assert names == {"100": "Первая", "101": "Вторая · обновлена"}

    with_db(check)


def test_quick_sync_keeps_positions_unique(monkeypatch) -> None:
    """Новые сделки дописываются в конец: позиции не сталкиваются с сохранёнными."""
    async def check(s: AsyncSession) -> None:
        portal = FakeBitrix([_raw("100", title="Первая"), _raw("101", title="Вторая")])
        monkeypatch.setattr(factory, "get_bitrix24", lambda: portal)
        await ingest.refresh_deals(s, full=True)

        portal.deals = [_raw("102", title="Третья"), _raw("103", title="Четвёртая")]
        await ingest.refresh_deals(s)

        positions = [d.position for d in (await s.execute(select(Deal))).scalars().all()]
        assert sorted(positions) == [0, 1, 2, 3]

    with_db(check)


def test_full_sync_removes_deals_gone_from_portal(monkeypatch) -> None:
    """Полная сверка убирает сделки, которых в портале больше нет."""
    async def check(s: AsyncSession) -> None:
        portal = FakeBitrix([_raw("100", title="Первая"), _raw("101", title="Вторая")])
        monkeypatch.setattr(factory, "get_bitrix24", lambda: portal)
        await ingest.refresh_deals(s, full=True)

        portal.deals = [_raw("100", title="Первая")]
        result = await ingest.refresh_deals(s, full=True)

        assert result["removed"] == 1
        assert portal.last_call["created_after"] and not portal.last_call["modified_after"]
        refs = {d.external_id for d in (await s.execute(select(Deal))).scalars().all()}
        assert refs == {"100"}

    with_db(check)


def test_sync_skipped_without_real_mode(monkeypatch) -> None:
    """В демо-режиме и без настроенного портала сверка ничего не делает."""
    async def check(s: AsyncSession) -> None:
        monkeypatch.setattr(
            factory, "get_bitrix24", lambda: FakeBitrix([_raw("100", title="Сделка")]))

        settings.data_source = "mock"
        assert (await ingest.refresh_deals(s))["skipped"] is True

        settings.data_source = "real"
        settings.bitrix24_webhook_url = ""
        assert (await ingest.refresh_deals(s))["skipped"] is True
        assert not (await s.execute(select(Deal))).scalars().all()

    with_db(check)
