"""Идемпотентная загрузка демо-данных в БД (mock-режим).

Сделки и каналы поступают через мок-адаптеры (как в боевом конвейере),
остальной контент (нарушения, менеджеры, KPI, инсайты, рекомендации,
минус-слова, настройки) загружается из app.seeds напрямую.

Запуск вручную:  python -m app.seed
"""

from __future__ import annotations

import asyncio

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.integrations import factory
from app.models import (
    AiInsight,
    Baseline,
    BudgetRec,
    Call,
    Campaign,
    Channel,
    Deal,
    KpiCard,
    ManagerControl,
    MinusWord,
    Payment,
    RegulationConfig,
    SettingsHistory,
    StageHistory,
    Task,
    Violation,
)
from app.seeds.budget_recs import BUDGET_RECS
from app.seeds.insights import INSIGHTS
from app.seeds.kpi import BASE, KPI_CARDS
from app.seeds.minus_words import build_minus_words
from app.seeds.monitor import MANAGERS_CTRL
from app.seeds.regulation import HISTORY, REGULATION
from app.services.clock import to_msk

logger = get_logger("lawyer.seed")

# Таблицы, очищаемые перед загрузкой (дети раньше родителей).
_CLEAR_ORDER = [
    StageHistory, Task, Payment, Call, Campaign,
    Deal, Channel, Violation, ManagerControl,
    Baseline, KpiCard, AiInsight, BudgetRec, MinusWord,
    SettingsHistory, RegulationConfig,
]


async def seed_all(session: AsyncSession) -> None:
    """Полностью пересобирает демо-данные в БД (идемпотентно)."""
    for model in _CLEAR_ORDER:
        await session.execute(delete(model))

    _seed_deals(session)
    _seed_channels(session)
    _seed_managers(session)
    _seed_kpi(session)
    _seed_insights(session)
    _seed_budget_recs(session)
    _seed_minus_words(session)
    _seed_regulation(session)

    await session.commit()
    logger.info("Демо-данные загружены в БД")


def _seed_deals(session: AsyncSession) -> None:
    for i, row in enumerate(factory.get_bitrix24().fetch_deals()):
        deal = Deal(
            position=i, on_dashboard=row.get("on_dashboard", True), ref=row.get("ref", ""),
            name=row["name"], src=row["src"], campaign=row.get("campaign"), utm=row.get("utm"),
            mgr=row["mgr"],
            status_label=row["status"][0], status_class=row["status"][1],
            first_contact=row["fc"],
            call=bool(row["call"]), invoice=bool(row["inv"]), paid=bool(row["pay"]),
            amount=row["sum"], risk=row["risk"], tags=row["tags"],
            ai_comment=row["ai"], refuse_reason=row["reason"],
            phone=row.get("phone"), stage=row.get("stage"),
            created_at=to_msk(row.get("created")),
            first_contact_at=to_msk(row.get("first_contact")),
            stage_entered_at=to_msk(row.get("stage_entered")),
            last_activity_at=to_msk(row.get("last_activity")),
        )
        if row.get("has_task"):
            deal.tasks.append(Task(
                title=f"Связаться по сделке «{row['name']}»",
                assignee=row["mgr"] if row["mgr"] != "—" else None,
                status="open",
            ))
        session.add(deal)


def _seed_channels(session: AsyncSession) -> None:
    for i, ch in enumerate(factory.get_yandex_direct().fetch_channels()):
        channel = Channel(
            position=i, name=ch["name"], color=ch["color"], spend=ch["spend"],
            leads=ch["leads"], deals=ch["deals"], payments=ch["payments"],
            revenue=ch["revenue"], margin=ch["margin"],
        )
        for j, camp in enumerate(ch.get("campaigns", [])):
            channel.campaigns.append(Campaign(
                position=j, name=camp["name"], spend=camp["spend"],
                leads=camp["leads"], deals=camp["deals"], payments=camp["payments"],
                revenue=camp["revenue"], margin=camp["margin"],
            ))
        session.add(channel)


def _seed_managers(session: AsyncSession) -> None:
    for i, m in enumerate(MANAGERS_CTRL):
        session.add(ManagerControl(
            position=i, name=m["name"], inwork=m["inwork"], overdue=m["overdue"],
            notask=m["notask"], fc=m["fc"], invoices=m["inv"], payments=m["pay"],
            paysum=m["paysum"], zone_label=m["zone"][0], zone_class=m["zone"][1],
        ))


def _seed_kpi(session: AsyncSession) -> None:
    for key, value in BASE.items():
        session.add(Baseline(key=key, value=float(value)))
    for i, c in enumerate(KPI_CARDS):
        session.add(KpiCard(
            position=i, key=c["key"], label=c["label"], icon=c["icon"], svg=c["svg"],
            kind=c["kind"], base_key=c.get("base_key"), scales=c["scales"],
            static_value=c.get("static_value"), trend=c["trend"], delta=c["delta"],
            spark=c["spark"], drill=c.get("drill"),
        ))


def _seed_insights(session: AsyncSession) -> None:
    for i, ins in enumerate(INSIGHTS):
        session.add(AiInsight(
            position=i, sev_label=ins["sev"][0], sev_class=ins["sev"][1],
            ic=ins["ic"], icon=ins["icon"], title=ins["title"], time=ins["time"],
            surface=ins["surface"], text=ins["text"], rec=ins["rec"],
            src=ins["src"], conf=ins["conf"], dep=ins["dep"],
        ))


def _seed_budget_recs(session: AsyncSession) -> None:
    for i, r in enumerate(BUDGET_RECS):
        session.add(BudgetRec(
            position=i, ic=r["ic"], svg=r["svg"], title=r["title"],
            tag_label=r["tag"][0], tag_class=r["tag"][1], text=r["text"],
            why=r["why"], impact=r["impact"], src=r["src"], conf=r["conf"], dep=r["dep"],
        ))


def _seed_minus_words(session: AsyncSession) -> None:
    for i, w in enumerate(build_minus_words()):
        session.add(MinusWord(
            position=i, phrase=w["phrase"], camp=w["camp"], level=w["level"],
            shows=w["shows"], clicks=w["clicks"], spend=w["spend"], conv=w["conv"],
            deals=w["deals"], reason=w["reason"], conf=w["conf"], status=w["status"],
        ))


def _seed_regulation(session: AsyncSession) -> None:
    session.add(RegulationConfig(id=1, data=REGULATION))
    for i, h in enumerate(HISTORY):
        session.add(SettingsHistory(
            position=i, dt=h["dt"], user=h["user"], param=h["param"],
            value_from=h["from"], value_to=h["to"], crit=h["crit"],
        ))


async def is_empty(session: AsyncSession) -> bool:
    """Пуста ли БД (нет ни одной сделки) — для авто-сида в mock-режиме."""
    count = await session.scalar(select(func.count()).select_from(Deal))
    return (count or 0) == 0


async def main() -> None:
    async with SessionLocal() as session:
        await seed_all(session)


if __name__ == "__main__":
    asyncio.run(main())
