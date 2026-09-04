"""Роутер дашборда: KPI, триаж, воронка, источники, таймсерии, ROMI, менеджеры, лиды."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, require_financial_access, require_session
from app.core.db import get_session
from app.services import business_settings, metrics, plan_fact

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_session)])

# Все витрины дашборда принимают одни и те же фильтры панели: период, менеджер
# и источник лида. Без mgr/source выпадающие списки не влияли ни на что, кроме
# таблицы лидов, — дашборд выглядел «замороженным» при их переключении.


async def _scoped_manager(
    session: AsyncSession, user: AuthUser, requested: str
) -> str | list[str]:
    """Накладывает область сотрудника/отдела поверх пользовательского фильтра."""
    if user.role == "owner":
        return requested
    config = await business_settings.get_settings(session)
    if user.role == "head":
        names = [
            str(item.get("name") or "") for item in config.get("employees", [])
            if item.get("enabled", True)
            and str(item.get("department_key") or "") == user.department_key
            and item.get("name")
        ]
        if requested != "all":
            return requested if requested in names else "__no_access__"
        return names or ["__no_access__"]
    employee = next(
        (item for item in config.get("employees", [])
         if str(item.get("key") or "") == user.employee_key),
        None,
    )
    # Непривязанная учётная запись не должна случайно получить общий набор данных.
    return str(employee.get("name") or "") if employee else "__no_access__"


@router.get("/kpis")
async def get_kpis(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
    user: AuthUser = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    mgr = await _scoped_manager(session, user, mgr)
    rows = await metrics.kpis(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity,
        funnel=funnel,
    )
    if user.role == "manager":
        rows = [row for row in rows if row.get("kind") != "money" and row.get("key") != "romi"]
    return rows


@router.get("/attention")
async def get_attention(
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
    user: AuthUser = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    mgr = await _scoped_manager(session, user, mgr)
    result = await metrics.attention(
        session, mgr=mgr, source=source, legal_entity=legal_entity, funnel=funnel
    )
    if user.role == "manager":
        result["money_at_risk"] = 0
        result["money_at_risk_display"] = "Скрыто"
    return result


@router.get("/filters")
async def get_filters(
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_session),
) -> dict[str, Any]:
    """Реальные опции фильтров (менеджеры/каналы/источники) из текущих данных."""
    result = await metrics.filter_options(session)
    if user.role in {"manager", "head"}:
        own = await _scoped_manager(session, user, "all")
        names = own if isinstance(own, list) else [own]
        result["managers"] = [name for name in names if name != "__no_access__"]
    return result


@router.get("/funnel")
async def get_funnel(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
    user: AuthUser = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    mgr = await _scoped_manager(session, user, mgr)
    return await metrics.funnel(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity,
        funnel=funnel,
    )


@router.get("/sources")
async def get_sources(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
    user: AuthUser = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    mgr = await _scoped_manager(session, user, mgr)
    return await metrics.sources(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity,
        funnel=funnel,
    )


@router.get("/revenue-series")
async def get_revenue_series(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
    session: AsyncSession = Depends(get_session),
    _: AuthUser = Depends(require_financial_access),
) -> dict[str, Any]:
    return await metrics.revenue_series(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity,
        funnel=funnel,
    )


@router.get("/romi-by-channel")
async def get_romi_by_channel(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
    session: AsyncSession = Depends(get_session),
    _: AuthUser = Depends(require_financial_access),
) -> list[dict[str, Any]]:
    return await metrics.romi_by_channel(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity,
        funnel=funnel,
    )


@router.get("/expenses-by-article")
async def get_expenses_by_article(
    period: str = "30",
    legal_entity: str = "all",
    funnel: str = "all",
    session: AsyncSession = Depends(get_session),
    _: AuthUser = Depends(require_financial_access),
) -> list[dict[str, Any]]:
    return await metrics.expenses_by_article(session, period, legal_entity)


@router.get("/managers")
async def get_managers(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
    user: AuthUser = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    mgr = await _scoped_manager(session, user, mgr)
    rows = await metrics.managers(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity,
        funnel=funnel,
    )
    if user.role == "manager":
        for row in rows:
            row.update(payments=0, paysum=0, paysum_display="Скрыто")
    return rows


@router.get("/leads")
async def get_leads(
    mgr: str = "all",
    source: str = "all",
    risk: str | None = None,
    period: str = "30",
    legal_entity: str = "all",
    funnel: str = "all",
    user: AuthUser = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    mgr = await _scoped_manager(session, user, mgr)
    rows = await metrics.leads(
        session,
        mgr=mgr,
        source=source,
        risk=risk,
        period=period,
        legal_entity=legal_entity,
        funnel=funnel,
    )
    if user.role == "manager":
        for row in rows:
            row.update(amount=0, amount_display="Скрыто")
    return rows


@router.get("/departments")
async def get_departments(
    period: str = "30",
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_session),
) -> list[dict[str, Any]]:
    if user.role == "manager":
        return []
    return await metrics.departments(
        session, period, mgr=mgr, source=source, legal_entity=legal_entity,
        funnel=funnel,
    )


@router.get("/plan-fact")
async def get_plan_fact(
    month: str | None = None,
    legal_entity: str = "all",
    funnel: str = "all",
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_session),
) -> list[dict[str, Any]]:
    selected_month = month or datetime.now(UTC).strftime("%Y-%m")
    try:
        result = await plan_fact.rows(
            session, selected_month, legal_entity=legal_entity, funnel=funnel
        )
        if user.role == "manager":
            result = [
                row for row in result
                if row.get("scope_type") == "employee" and row.get("scope_key") == user.employee_key
            ]
            for row in result:
                for section in ("plan", "fact", "completion"):
                    row[section]["revenue"] = None
                    row[section]["payments"] = None
        elif user.role == "head":
            result = [
                row for row in result
                if row.get("scope_type") == "department"
                and row.get("scope_key") == user.department_key
            ]
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
