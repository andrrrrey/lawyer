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

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdCost, Deal, ManualExpense, OneCReceipt
from app.services import ingest
from app.services import period as per

FilterValue = str | list[str]


def _values(value: FilterValue) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if item and item != "all"]
    return [] if not value or value == "all" else [value]


def _funnel_clause(values: FilterValue):
    clauses = []
    for value in _values(values):
        crm_source, separator, funnel_id = value.partition(":")
        if separator and crm_source and funnel_id:
            clauses.append(and_(Deal.crm_source == crm_source, Deal.funnel_id == funnel_id))
    return or_(*clauses) if clauses else None


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
        "source": deal.src,
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
    mgr: FilterValue = "all",
    source: str = "all",
    legal_entity: FilterValue = "all",
    funnel: FilterValue = "all",
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
    legal_values = _values(legal_entity)
    if legal_values:
        cost_where.append(AdCost.legal_entity_key.in_(legal_values))
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
    if legal_values:
        manual_where.append(ManualExpense.legal_entity_key.in_(legal_values))
    manual = (
        await session.execute(select(ManualExpense).where(*manual_where))
    ).scalars().all()
    cost_rows.extend(
        {
            "campaign": row.campaign or row.article,
            "campaign_id": None,
            "channel": row.channel,
            # Для ручного рекламного расхода channel хранит выбранный SOURCE_ID
            # сделки. Название поля оставлено для обратной совместимости API/БД.
            "source": row.channel,
            "spend": round(row.amount),
            "clicks": 0,
            "impressions": 0,
        }
        for row in manual
    )

    stmt = select(Deal).where(Deal.created_at.is_not(None), Deal.created_at >= start)
    if end is not None:
        stmt = stmt.where(Deal.created_at < end)
    manager_values = _values(mgr)
    if manager_values:
        stmt = stmt.where(Deal.mgr.in_(manager_values))
    if source and source != "all":
        stmt = stmt.where(Deal.src == source)
    if legal_values:
        stmt = stmt.where(Deal.legal_entity_key.in_(legal_values))
    funnel_clause = _funnel_clause(funnel)
    if funnel_clause is not None:
        stmt = stmt.where(funnel_clause)
    deals = (await session.execute(stmt)).scalars().all()

    receipt_where = [
        OneCReceipt.excluded.is_(False),
        OneCReceipt.registrar_date.is_not(None),
        OneCReceipt.registrar_date >= start,
    ]
    if end is not None:
        receipt_where.append(OneCReceipt.registrar_date < end)
    if legal_values:
        receipt_where.append(OneCReceipt.legal_entity_key.in_(legal_values))
    if _values(funnel):
        # Поступления без связанной сделки нельзя достоверно отнести к воронке.
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
