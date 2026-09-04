"""Витрина каналов/кампаний за выбранный период.

Сохранённые строки Channel/Campaign — итог последнего пересчёта за всё окно
выгрузки источников, поэтому напрямую они не отвечают на переключатель периода.
Здесь витрина пересобирается на лету из посуточного сырья Директа (AdCost) и
сделок, попавших в тот же период. Если посуточного сырья нет (пересчёт ещё не
выполнялся после обновления или Директ не подключён), возвращается None —
вызывающий код показывает сохранённые строки.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdCost, Deal, ManualExpense, OneCReceipt
from app.services import ingest
from app.services import period as per


async def has_daily_costs(session: AsyncSession) -> bool:
    """Есть ли датированные расходы Директа или ручные рекламные расходы."""
    direct = await session.scalar(select(func.count()).select_from(AdCost))
    manual = await session.scalar(
        select(func.count()).select_from(ManualExpense).where(
            ManualExpense.include_in_romi.is_(True)
        )
    )
    return bool(direct or manual)


def deal_row(deal: Deal) -> dict:
    """Сделка из БД → запись в форме, которую ждёт агрегатор конвейера."""
    return {
        "campaign": deal.campaign,
        "external_id": deal.external_id,
        "amount": int(deal.amount or 0),
        # Семантика успеха в БД хранится классом статуса (см. ingest._stage_class).
        "semantic": "S" if deal.status_class == "st-ok" else None,
        "custom": deal.custom or {},
    }


async def for_period(
    session: AsyncSession,
    period: str,
    *,
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
) -> list[dict] | None:
    """Каналы/кампании за период или None, если посуточного сырья ещё нет."""
    if not await has_daily_costs(session):
        return None

    now = datetime.now(UTC)
    start = per.start(period, now)
    end = per.end(period, now)
    cost_where = [AdCost.date.is_not(None), AdCost.date >= start]
    if end is not None:
        cost_where.append(AdCost.date < end)
    if legal_entity and legal_entity != "all":
        cost_where.append(AdCost.legal_entity_key == legal_entity)
    costs = (await session.execute(
        select(AdCost).where(*cost_where)
    )).scalars().all()
    cost_rows = [
        {
            "campaign": c.campaign, "campaign_id": c.campaign_id,
            # Расход в AdCost уже приведён к базе без НДС.
            "spend": c.spend, "clicks": c.clicks, "impressions": c.impressions,
        }
        for c in costs
    ]

    manual_where = [
        ManualExpense.include_in_romi.is_(True),
        ManualExpense.spent_at >= start,
    ]
    if end is not None:
        manual_where.append(ManualExpense.spent_at < end)
    if legal_entity and legal_entity != "all":
        manual_where.append(ManualExpense.legal_entity_key == legal_entity)
    manual = (
        await session.execute(select(ManualExpense).where(*manual_where))
    ).scalars().all()
    cost_rows.extend(
        {
            "campaign": row.campaign or row.article,
            "campaign_id": None,
            "channel": row.channel,
            "spend": round(row.amount),
            "clicks": 0,
            "impressions": 0,
        }
        for row in manual
    )

    stmt = select(Deal).where(Deal.created_at.is_not(None), Deal.created_at >= start)
    if end is not None:
        stmt = stmt.where(Deal.created_at < end)
    if mgr and mgr != "all":
        stmt = stmt.where(Deal.mgr == mgr)
    if source and source != "all":
        stmt = stmt.where(Deal.src == source)
    if legal_entity and legal_entity != "all":
        stmt = stmt.where(Deal.legal_entity_key == legal_entity)
    if funnel and funnel != "all":
        crm_source, separator, funnel_id = funnel.partition(":")
        if separator and crm_source and funnel_id:
            stmt = stmt.where(
                Deal.crm_source == crm_source,
                Deal.funnel_id == funnel_id,
            )
    deals = (await session.execute(stmt)).scalars().all()

    receipt_where = [
        OneCReceipt.excluded.is_(False),
        OneCReceipt.registrar_date.is_not(None),
        OneCReceipt.registrar_date >= start,
    ]
    if end is not None:
        receipt_where.append(OneCReceipt.registrar_date < end)
    if legal_entity and legal_entity != "all":
        receipt_where.append(OneCReceipt.legal_entity_key == legal_entity)
    if funnel and funnel != "all":
        # Поступления без связанной сделки нельзя достоверно отнести к воронке.
        crm_source, separator, funnel_id = funnel.partition(":")
        if separator and crm_source and funnel_id:
            allowed_deal_ids = {deal.id for deal in deals}
            receipt_where.append(OneCReceipt.matched_deal_id.in_(allowed_deal_ids))
    receipts = (
        await session.execute(select(OneCReceipt).where(*receipt_where))
    ).scalars().all()
    receipt_rows = [
        {
            "crm_external_id": row.crm_external_id,
            "amount": row.amount,
            "excluded": row.excluded,
        }
        for row in receipts
    ]
    return ingest.aggregate_channels(
        cost_rows, [deal_row(deal) for deal in deals], receipt_rows
    )
