"""Роутер дашборда: KPI, триаж, воронка, источники, таймсерии, ROMI, менеджеры, лиды."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_session
from app.core.db import get_session
from app.services import metrics

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_session)])

# Все витрины дашборда принимают одни и те же фильтры панели: период, менеджер
# и источник лида. Без mgr/source выпадающие списки не влияли ни на что, кроме
# таблицы лидов, — дашборд выглядел «замороженным» при их переключении.


@router.get("/kpis")
async def get_kpis(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await metrics.kpis(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity
    )


@router.get("/attention")
async def get_attention(
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await metrics.attention(
        session, mgr=mgr, source=source, legal_entity=legal_entity
    )


@router.get("/filters")
async def get_filters(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Реальные опции фильтров (менеджеры/каналы/источники) из текущих данных."""
    return await metrics.filter_options(session)


@router.get("/funnel")
async def get_funnel(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await metrics.funnel(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity
    )


@router.get("/sources")
async def get_sources(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await metrics.sources(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity
    )


@router.get("/revenue-series")
async def get_revenue_series(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await metrics.revenue_series(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity
    )


@router.get("/romi-by-channel")
async def get_romi_by_channel(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await metrics.romi_by_channel(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity
    )


@router.get("/expenses-by-article")
async def get_expenses_by_article(
    period: str = "30",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await metrics.expenses_by_article(session, period, legal_entity)


@router.get("/managers")
async def get_managers(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await metrics.managers(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity
    )


@router.get("/leads")
async def get_leads(
    mgr: str = "all",
    source: str = "all",
    risk: str | None = None,
    period: str = "30",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await metrics.leads(
        session,
        mgr=mgr,
        source=source,
        risk=risk,
        period=period,
        legal_entity=legal_entity,
    )
