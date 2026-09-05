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
from copy import deepcopy
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 — регистрирует таблицы
from app.core.config import settings
from app.core.db import Base
from app.integrations import factory
from app.models import CrmActivity, Deal, StageHistory, Task
from app.seeds.business import BUSINESS_SETTINGS
from app.services import business_settings, ingest

DB_PATH = pathlib.Path(tempfile.gettempdir()) / "lawyer_sync_test.db"


def test_datetime_identity_normalizes_timezone() -> None:
    """Один момент времени не дублируется из-за часового пояса Bitrix."""
    bitrix_time = datetime.fromisoformat("2026-08-04T15:00:00+03:00")
    database_time = datetime.fromisoformat("2026-08-04T12:00:00+00:00")

    assert ingest._dt_identity(bitrix_time) == ingest._dt_identity(database_time)


def test_stage_history_long_name_is_idempotent(monkeypatch) -> None:
    """Длинное название стадии сравнивается в том же виде, что хранится в БД."""
    async def check(s: AsyncSession) -> None:
        portal = FakeBitrix([_raw("100", title="Сделка", stage="LONG")])
        portal.history = [{
            "external_id": "h1",
            "deal_external_id": "100",
            "stage_id": "LONG",
            "changed_at": "2026-08-01T10:00:00+03:00",
        }]
        portal.stages = [
            {"id": "LONG", "name": "Очень длинное название стадии " * 4}
        ]
        monkeypatch.setattr(factory, "get_bitrix24", lambda: portal)

        await ingest.refresh_deals(s, full=True)
        result = await ingest.refresh_deals(s, full=True)

        assert result["timeline"]["primary"]["history_created"] == 0
        rows = (await s.execute(select(StageHistory))).scalars().all()
        assert len(rows) == 1
        assert len(rows[0].to_stage) == 64

    with_db(check)


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
        self.users = [{"id": "12", "name": "Михаил Иванов"}]
        self.history: list[dict] = []
        self.activities: list[dict] = []
        self.stages = [
            {"id": "NEW", "name": "Новое обращение"},
            {"id": "WON", "name": "Оплачено"},
        ]
        self.last_call: dict[str, Any] = {}

    def fetch_deals(self, created_after=None, extra_fields=None, modified_after=None):
        self.last_call = {"created_after": created_after, "modified_after": modified_after}
        return [dict(d) for d in self.deals]

    def fetch_users(self):
        return [dict(row) for row in self.users]

    def fetch_stages(self):
        return [dict(row) for row in self.stages]

    def fetch_sources(self):
        return [{"id": "site", "name": "Сайт"}]

    def fetch_contact_phones(self, contact_ids):  # noqa: ARG002
        return {}

    def fetch_stage_history(self, deal_ids=None, changed_after=None):  # noqa: ARG002
        return [dict(row) for row in self.history]

    def fetch_activities(self, deal_ids, modified_after=None):  # noqa: ARG002
        return [dict(row) for row in self.activities]

    def fetch_open_action_deal_ids(self, deal_ids):  # noqa: ARG002
        return set()


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

        assert {key: result[key] for key in ("skipped", "created", "updated", "removed", "full")} == {
            "skipped": False, "created": 0, "updated": 1, "removed": 0, "full": False,
        }
        deal = (await s.execute(select(Deal))).scalar_one()
        assert deal.id == deal_id           # строка обновлена, а не пересоздана
        assert deal.amount == 145_000       # новые данные приехали
        assert deal.status_class == "st-ok"
        # Задача на месте — иначе «сделка без задачи» вернулась бы в мониторинг.
        assert (await s.execute(select(Task))).scalars().all()

    with_db(check)


def test_sync_stage_history_and_activities_is_idempotent(monkeypatch) -> None:
    """История/контакты сохраняются один раз и формируют фактические SLA-даты."""
    async def check(s: AsyncSession) -> None:
        portal = FakeBitrix([_raw("100", title="Сделка", stage="WON")])
        portal.history = [
            {
                "external_id": "h1", "deal_external_id": "100", "stage_id": "NEW",
                "changed_at": "2026-08-01T10:00:00+03:00",
            },
            {
                "external_id": "h2", "deal_external_id": "100", "stage_id": "WON",
                "changed_at": "2026-08-04T12:00:00+03:00",
            },
        ]
        portal.activities = [
            {
                "external_id": "a1", "deal_external_id": "100", "kind": "call",
                "subject": "Исходящий звонок", "responsible_id": "12",
                "occurred_at": "2026-08-01T10:12:00+03:00",
                "ended_at": "2026-08-01T10:15:00+03:00", "duration_sec": 180,
                "completed": True, "direction": "2", "provider_id": "CRM_CALL",
            },
            {
                "external_id": "a2", "deal_external_id": "100", "kind": "meeting",
                "subject": "Встреча", "responsible_id": "12",
                "occurred_at": "2026-08-03T13:00:00+03:00",
                "ended_at": "2026-08-03T14:00:00+03:00", "duration_sec": 3600,
                "completed": True, "direction": "", "provider_id": "CRM_MEETING",
            },
        ]
        monkeypatch.setattr(factory, "get_bitrix24", lambda: portal)

        first = await ingest.refresh_deals(s, full=True)
        second = await ingest.refresh_deals(s, full=True)

        assert first["timeline"]["primary"]["history_created"] == 2
        assert first["timeline"]["primary"]["activities_created"] == 2
        assert second["timeline"]["primary"]["history_created"] == 0
        assert second["timeline"]["primary"]["activities_created"] == 0
        assert len((await s.execute(select(StageHistory))).scalars().all()) == 2
        assert len((await s.execute(select(CrmActivity))).scalars().all()) == 2
        deal = (await s.execute(select(Deal))).scalar_one()
        assert deal.first_contact == "12 мин"
        assert deal.call is True
        assert deal.first_contact_at.isoformat().startswith("2026-08-01T10:12:00")
        assert deal.last_activity_at.isoformat().startswith("2026-08-03T13:00:00")
        assert deal.stage_entered_at.isoformat().startswith("2026-08-04T12:00:00")

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


def test_quick_sync_repairs_names_on_deals_outside_changed_batch(monkeypatch) -> None:
    """После выдачи user_brief ФИО чинятся у всех сделок, не только изменённых."""
    async def check(s: AsyncSession) -> None:
        portal = FakeBitrix([_raw("100", title="Старая", mgr="12")])
        portal.users = []
        monkeypatch.setattr(factory, "get_bitrix24", lambda: portal)
        await ingest.refresh_deals(s, full=True)
        deal = (await s.execute(select(Deal))).scalar_one()
        assert deal.mgr == "Сотрудник #12"

        # Сделка 100 не попала в короткую выборку изменённых, но справочник уже
        # доступен: плановый sync должен обновить сохранённое имя.
        portal.users = [{"id": "12", "name": "Михаил Иванов"}]
        portal.deals = []
        await ingest.refresh_deals(s)

        deal = (await s.execute(select(Deal))).scalar_one()
        assert deal.mgr == "Михаил Иванов"

    with_db(check)


def test_business_settings_mapping_repairs_saved_manager_name(monkeypatch) -> None:
    """Ручное соответствие ID → ФИО применяется без полного пересчёта."""
    async def check(s: AsyncSession) -> None:
        portal = FakeBitrix([_raw("100", title="Сделка", mgr="12")])
        portal.users = []
        monkeypatch.setattr(factory, "get_bitrix24", lambda: portal)
        await ingest.refresh_deals(s, full=True)
        deal = (await s.execute(select(Deal))).scalar_one()
        deal.crm_source = "box"
        await s.commit()

        config = deepcopy(BUSINESS_SETTINGS)
        config["employees"] = [{
            "key": "box_12",
            "name": "Михаил Иванов",
            "crm_source": "box",
            "bitrix_user_id": "12",
            "legal_entity_key": "",
            "department_key": "",
            "enabled": True,
        }]
        await business_settings.save_settings(s, config)

        deal = (await s.execute(select(Deal))).scalar_one()
        assert deal.mgr == "Михаил Иванов"

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
