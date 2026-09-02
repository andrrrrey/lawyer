"""Переключатель периода и фильтры дашборда в боевом режиме.

Проверяется, что расход/клики/визиты считаются по посуточному сырью источников
за выбранный период (а не отдаются одним итогом на все периоды) и что фильтры
«менеджер»/«источник» действительно сужают витрины, а не только таблицу лидов.
"""

from __future__ import annotations

import asyncio
import pathlib
import tempfile
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 — регистрирует таблицы
from app.core.config import settings
from app.core.db import Base
from app.models import AdCost, Deal, Visit
from app.services import analytics, metrics

DB_PATH = pathlib.Path(tempfile.gettempdir()) / "lawyer_period_test.db"

NOW = datetime.now(UTC)


def _deal(pos: int, *, days_ago: int, mgr: str, src: str, amount: int,
          campaign: str = "10", won: bool = True) -> Deal:
    return Deal(
        position=pos, on_dashboard=True, ref=f"Сделка #{pos}", external_id=str(pos),
        name=f"Сделка {pos}", src=src, mgr=mgr, campaign=campaign,
        status_label="Оплачено" if won else "В работе",
        status_class="st-ok" if won else "st-mid",
        stage="Оплачено" if won else "В работе", amount=amount,
        created_at=NOW - timedelta(days=days_ago),
    )


def _cost(days_ago: int, *, spend: int, clicks: int) -> AdCost:
    return AdCost(
        date=NOW - timedelta(days=days_ago), campaign="Поиск · Бренд",
        campaign_id="10", spend=spend, clicks=clicks, impressions=clicks * 10,
    )


async def _seed(session: AsyncSession) -> None:
    # По одной сделке в каждом окне периода: сегодня / 7 дней / 30 дней / квартал.
    session.add_all([
        _deal(1, days_ago=0, mgr="Иванов", src="Сайт", amount=100_000),
        _deal(2, days_ago=3, mgr="Петров", src="Звонок", amount=200_000),
        _deal(3, days_ago=20, mgr="Иванов", src="Сайт", amount=300_000),
        _deal(4, days_ago=60, mgr="Петров", src="Сайт", amount=400_000),
    ])
    # Расход и клики — по дню; визиты — агрегат Метрики по дню.
    session.add_all([
        _cost(0, spend=1_000, clicks=10),
        _cost(3, spend=2_000, clicks=20),
        _cost(20, spend=3_000, clicks=30),
        _cost(60, spend=4_000, clicks=40),
    ])
    session.add_all([
        Visit(date=NOW - timedelta(days=d), source="Переходы из поисковых систем", visits=v)
        for d, v in ((0, 100), (3, 200), (20, 300), (60, 400))
    ])
    await session.commit()


def with_real_data(check: Callable[[AsyncSession], Coroutine[Any, Any, None]]) -> None:
    """Прогоняет проверку на отдельной БД в боевом режиме (DATA_SOURCE=real)."""
    async def run() -> None:
        if DB_PATH.exists():
            DB_PATH.unlink()
        engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", poolclass=NullPool)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        previous = settings.data_source
        settings.data_source = "real"
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with maker() as session:
                await _seed(session)
                await check(session)
        finally:
            settings.data_source = previous
            await engine.dispose()
            if DB_PATH.exists():
                DB_PATH.unlink()

    asyncio.run(run())


def test_ad_metrics_follow_period() -> None:
    """Расход/клики/визиты растут вместе с окном периода, а не повторяются."""
    async def check(s: AsyncSession) -> None:
        today = await metrics._ad_totals(s, "today")
        week = await metrics._ad_totals(s, "7")
        month = await metrics._ad_totals(s, "30")
        quarter = await metrics._ad_totals(s, "quarter")

        assert today["clicks"] == 10
        assert week["clicks"] == 30       # 10 + 20
        assert month["clicks"] == 60      # + 30
        assert quarter["clicks"] == 100   # + 40

        assert today["spend"] == 1_000
        assert quarter["spend"] == 10_000
        assert [today["visits"], week["visits"], month["visits"], quarter["visits"]] \
            == [100, 300, 600, 1_000]

    with_real_data(check)


def test_ad_metrics_fall_back_without_daily_rows() -> None:
    """Без посуточного сырья показатели берутся из сохранённых итогов, а не обнуляются."""
    async def check(s: AsyncSession) -> None:
        from sqlalchemy import delete

        from app.models import Baseline
        await s.execute(delete(AdCost))
        await s.execute(delete(Visit))
        s.add_all([Baseline(key="clicks", value=777), Baseline(key="visits", value=888)])
        await s.commit()

        totals = await metrics._ad_totals(s, "today")
        assert totals["clicks"] == 777
        assert totals["visits"] == 888

    with_real_data(check)


def test_kpis_follow_period_and_filters() -> None:
    """Лиды и выручка отвечают и на период, и на выбор менеджера/источника."""
    async def check(s: AsyncSession) -> None:
        month = await metrics._period_baseline(s, "30")
        assert month["leads"] == 3
        assert month["revenue"] == 600_000

        today = await metrics._period_baseline(s, "today")
        assert today["leads"] == 1
        assert today["revenue"] == 100_000

        by_mgr = await metrics._period_baseline(s, "30", mgr="Иванов")
        assert by_mgr["leads"] == 2
        assert by_mgr["revenue"] == 400_000

        by_src = await metrics._period_baseline(s, "30", source="Звонок")
        assert by_src["leads"] == 1
        assert by_src["revenue"] == 200_000

        # Рекламные показатели не разрезаются менеджером — расход относится к
        # кампании, а не к ответственному.
        assert by_mgr["spend"] == month["spend"]

    with_real_data(check)


def test_sources_donut_follows_filters() -> None:
    """Диаграмма источников считается по сделкам и следует фильтрам."""
    async def check(s: AsyncSession) -> None:
        month = {r["name"]: r["leads"] for r in await metrics.sources(s, "30")}
        assert month == {"Сайт": 2, "Звонок": 1}

        only_ivanov = {r["name"]: r["leads"] for r in await metrics.sources(s, "30", mgr="Иванов")}
        assert only_ivanov == {"Сайт": 2}

    with_real_data(check)


def test_managers_follow_period() -> None:
    """Таблица менеджеров ограничена периодом и фильтром менеджера."""
    async def check(s: AsyncSession) -> None:
        month = {m["name"] for m in await metrics.managers(s, "30")}
        assert month == {"Иванов", "Петров"}

        today = {m["name"] for m in await metrics.managers(s, "today")}
        assert today == {"Иванов"}

        picked = {m["name"] for m in await metrics.managers(s, "30", mgr="Петров")}
        assert picked == {"Петров"}

    with_real_data(check)


def test_channels_table_follows_period() -> None:
    """Сводка по каналам пересобирается под период, а не остаётся итогом окна."""
    async def check(s: AsyncSession) -> None:
        month = await analytics.channels_table(s, period="30")
        assert len(month) == 1
        assert month[0]["name"] == "Яндекс Директ — Поиск"
        assert month[0]["spend"] == 6_000   # 1000 + 2000 + 3000
        # Дневные строки одной кампании свёрнуты в одну строку таблицы.
        assert len(month[0]["campaigns"]) == 1
        assert month[0]["leads"] == 3

        today = await analytics.channels_table(s, period="today")
        assert today[0]["spend"] == 1_000
        assert today[0]["leads"] == 1

        quarter = await analytics.channels_table(s, period="quarter")
        assert quarter[0]["spend"] == 10_000
        assert quarter[0]["leads"] == 4

    with_real_data(check)


def test_chain_follows_period() -> None:
    """Первые шаги цепочки (реклама/визиты) меняются вместе с периодом."""
    async def check(s: AsyncSession) -> None:
        by_period = {}
        for period in ("today", "7", "30", "quarter"):
            steps = await analytics.chain(s, period)
            by_period[period] = (steps[0]["display"], steps[1]["display"])

        # Раньше здесь на всех периодах стояло одно и то же 30-дневное значение.
        assert len({v for v in by_period.values()}) == 4

    with_real_data(check)


def test_custom_period_exact_date_and_interval() -> None:
    """Кастомный период: точная дата и интервал ограничивают выборку сверху и снизу.

    Сиды: сделки с days_ago = 0, 3, 20, 60. Проверяем, что `date:`/`range:`
    отбирают ровно те сделки, чьи created_at попадают в границы (включительно).
    """
    async def check(s: AsyncSession) -> None:
        def day(days_ago: int) -> str:
            return (NOW - timedelta(days=days_ago)).date().isoformat()

        # Точная дата: только сделка, созданная 3 дня назад (amount 200_000).
        exact = await metrics._period_baseline(s, f"date:{day(3)}")
        assert exact["leads"] == 1
        assert exact["revenue"] == 200_000

        # Интервал 3..20 дней назад включительно: сделки #2 и #3.
        interval = await metrics._period_baseline(s, f"range:{day(20)}:{day(3)}")
        assert interval["leads"] == 2
        assert interval["revenue"] == 500_000  # 200_000 + 300_000

        # Таблица лидов следует тем же границам.
        assert len(await metrics.leads(s, period=f"date:{day(0)}")) == 1
        assert len(await metrics.leads(s, period=f"range:{day(60)}:{day(0)}")) == 4

        # Диаграмма источников уважает верхнюю границу: сделка #4 (60 дней, «Сайт»)
        # выпадает из окна 0..20, остаётся только «Сайт»×2 и «Звонок»×1.
        donut = {r["name"]: r["leads"] for r in await metrics.sources(s, f"range:{day(20)}:{day(0)}")}
        assert donut == {"Сайт": 2, "Звонок": 1}

    with_real_data(check)


def test_custom_period_ad_totals_windowed() -> None:
    """Расход/клики/визиты кастомного интервала ограничены и сверху, и снизу."""
    async def check(s: AsyncSession) -> None:
        def day(days_ago: int) -> str:
            return (NOW - timedelta(days=days_ago)).date().isoformat()

        # Интервал 3..20 дней назад: расход по дням 3 и 20 (2000 + 3000).
        totals = await metrics._ad_totals(s, f"range:{day(20)}:{day(3)}")
        assert totals["spend"] == 5_000
        assert totals["clicks"] == 50   # 20 + 30
        assert totals["visits"] == 500  # 200 + 300

    with_real_data(check)


def test_filter_options_hide_uncountable_sources() -> None:
    """Источник без учитываемых сделок не попадает в фильтр (случай «cpc = везде 0»).

    Витрины считают только сделки дашборда с распознанной датой создания. Источник,
    у которого все сделки либо не на дашборде, либо без created_at, не должен
    предлагаться в списке — иначе его выбор обнуляет дашборд при любом периоде.
    """
    async def check(s: AsyncSession) -> None:
        # cpc: на дашборде, но без даты создания (DATE_CREATE не распознан) —
        # не учитывается ни одной витриной при любом периоде.
        s.add(Deal(
            position=90, on_dashboard=True, ref="cpc-1", external_id="90",
            name="cpc без даты", src="cpc", mgr="Иванов",
            status_label="В работе", status_class="st-mid", stage="В работе",
            amount=0, created_at=None,
        ))
        # partner: сделка есть, но не на дашборде.
        s.add(Deal(
            position=91, on_dashboard=False, ref="partner-1", external_id="91",
            name="partner off", src="partner", mgr="Иванов",
            status_label="В работе", status_class="st-mid", stage="В работе",
            amount=0, created_at=NOW,
        ))
        await s.commit()

        opts = await metrics.filter_options(s)
        assert "cpc" not in opts["sources"]
        assert "partner" not in opts["sources"]
        # Обычные источники сидов остаются доступны.
        assert {"Сайт", "Звонок"} <= set(opts["sources"])

    with_real_data(check)


@pytest.mark.parametrize("period", ["today", "7", "30", "quarter"])
def test_leads_table_follows_period(period: str) -> None:
    """Таблица лидов не выходит за границы выбранного периода."""
    async def check(s: AsyncSession) -> None:
        expected = {"today": 1, "7": 2, "30": 3, "quarter": 4}[period]
        assert len(await metrics.leads(s, period=period)) == expected

    with_real_data(check)
