"""Тесты движка регламента, админ-записи/отката и создания задач (изолированная БД)."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.core.config import settings
from app.core.db import Base
from app.models import Deal
from app.seed import seed_all
from app.services import admin, content, monitor
from app.services import violations as vio


def with_seeded(callback: Callable[[AsyncSession], Awaitable[None]]) -> None:
    async def run() -> None:
        settings.data_source = "mock"
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=NullPool)
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            maker = async_sessionmaker(bind=conn, expire_on_commit=False)
            async with maker() as session:
                await seed_all(session)
                return await callback(session)

    return asyncio.run(run())


def _ptypes(regular: list[dict]) -> list[str]:
    return [v["ptype"] for v in regular]


def test_engine_matches_prototype() -> None:
    async def check(s: AsyncSession) -> None:
        res = await vio.evaluate_current(s)
        assert len(res["regular"]) == 6
        assert len(res["review"]) == 2
        assert vio.money_at_risk(res["regular"]) == 241000
        assert set(_ptypes(res["regular"])) == {
            "overdue_contact", "no_task", "stuck", "no_recontact", "fields", "dup"
        }
        assert all(v["violation_at"] is not None for v in res["regular"])
        assert {v["ptype"] for v in res["review"]} == {"spam", "refusal"}

    with_seeded(check)


def test_threshold_sensitivity() -> None:
    async def check(s: AsyncSession) -> None:
        base = await vio.evaluate_current(s)
        assert _ptypes(base["regular"]).count("overdue_contact") == 1

        cfg = copy.deepcopy(await content.regulation(s))
        cfg["thresholds"][0]["v"] = 60  # первый контакт 15 → 60 мин
        await admin.update_regulation(s, cfg, user="admin")

        after = await vio.evaluate_current(s)
        # Королёв (47 мин) больше не «просрочка первого контакта»
        assert _ptypes(after["regular"]).count("overdue_contact") == 0

    with_seeded(check)


def test_failed_semantic_stage_is_not_an_active_violation() -> None:
    """Проваленная стадия исключается по семантике, даже при необычном названии."""
    async def check(s: AsyncSession) -> None:
        deal = (await s.execute(select(Deal).limit(1))).scalar_one()
        deal.stage = "Сделка провалена"
        deal.status_label = deal.stage
        deal.status_class = "st-bad"
        deal.stage_entered_at = deal.created_at
        deal.amount = 50_000_000
        await s.commit()

        result = await vio.evaluate_current(s)
        assert not any(item["ref"] == deal.ref for item in result["regular"])

    with_seeded(check)


def test_admin_history_and_rollback() -> None:
    async def check(s: AsyncSession) -> None:
        cfg = copy.deepcopy(await content.regulation(s))
        cfg["evaluative"]["stuck_days"] = 10
        res = await admin.update_regulation(s, cfg, user="admin")
        assert res["changes"] == 1

        hist = await content.history(s)
        top = hist[0]
        assert top["param"] == "Порог «зависшей» сделки"
        assert top["can_rollback"] is True

        await admin.rollback(s, top["id"], user="admin")
        restored = await content.regulation(s)
        assert restored["evaluative"]["stuck_days"] == 5

    with_seeded(check)


def test_admin_validation_rejects_bad_config() -> None:
    async def check(s: AsyncSession) -> None:
        cfg = copy.deepcopy(await content.regulation(s))
        cfg["thresholds"][0]["v"] = "не число"
        with pytest.raises(ValueError):
            await admin.update_regulation(s, cfg, user="admin")

    with_seeded(check)


def test_create_task_clears_no_task() -> None:
    async def check(s: AsyncSession) -> None:
        before = await vio.evaluate_current(s)
        assert "no_task" in _ptypes(before["regular"])  # ТеплоДом

        out = await monitor.create_task_for(s, "Сделка #3390")
        assert out["ok"] is True and out["assignee"]

        after = await vio.evaluate_current(s)
        assert "no_task" not in _ptypes(after["regular"])
        assert len(after["regular"]) == 5

    with_seeded(check)


def test_bitrix_open_action_clears_no_task() -> None:
    """Открытая задача/дело в Битрикс24 (флаг has_open_action) гасит «без задачи».

    Эмулирует боевой сценарий: у сделки в портале реально стоит задача или дело,
    синхронизация выставила has_open_action — движок не должен помечать no_task.
    """
    async def check(s: AsyncSession) -> None:
        before = await vio.evaluate_current(s)
        assert "no_task" in _ptypes(before["regular"])  # ТеплоДом

        deal = (await s.execute(
            select(Deal).where(Deal.ref == "Сделка #3390")
        )).scalar_one()
        deal.has_open_action = True
        await s.commit()

        after = await vio.evaluate_current(s)
        assert "no_task" not in _ptypes(after["regular"])
        assert len(after["regular"]) == 5

    with_seeded(check)


def test_create_task_unknown_ref() -> None:
    async def check(s: AsyncSession) -> None:
        with pytest.raises(ValueError):
            await monitor.create_task_for(s, "Сделка #0000")

    with_seeded(check)
