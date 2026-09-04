"""Месячный план-факт компании, отделов и сотрудников."""

from __future__ import annotations

import calendar
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import CrmActivity, Deal, OneCReceipt
from app.services import business_settings

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_METRICS = ("revenue", "payments", "deals", "calls", "meetings")


def _bounds(month: str) -> tuple[datetime, datetime]:
    match = _MONTH_RE.fullmatch(month)
    if match is None:
        raise ValueError("Месяц должен быть в формате ГГГГ-ММ")
    year, number = int(match[1]), int(match[2])
    start = datetime(year, number, 1, tzinfo=UTC)
    last = calendar.monthrange(year, number)[1]
    return start, datetime(year, number, last, 23, 59, 59, 999999, tzinfo=UTC)


def _employee_condition(employees: list[dict[str, Any]]):
    identities = [
        and_(
            Deal.crm_source == str(item.get("crm_source") or ""),
            Deal.mgr_id == str(item.get("bitrix_user_id") or ""),
        )
        for item in employees
        if item.get("enabled", True)
        and item.get("crm_source")
        and item.get("bitrix_user_id")
    ]
    return or_(*identities) if identities else false()


def _funnel_condition(funnel: str):
    source, separator, funnel_id = funnel.partition(":")
    if funnel == "all" or not separator or not source or not funnel_id:
        return None
    return and_(Deal.crm_source == source, Deal.funnel_id == funnel_id)


def _completion(plan: int, fact: float) -> float | None:
    return round(fact / plan * 100, 1) if plan > 0 else None


async def rows(
    session: AsyncSession,
    month: str,
    *,
    legal_entity: str = "all",
    funnel: str = "all",
) -> list[dict[str, Any]]:
    """Возвращает настроенные планы и рассчитанный факт за один месяц."""
    start, end = _bounds(month)
    config = await business_settings.get_settings(session)
    employees = config.get("employees", [])
    employees_by_key = {str(item.get("key")): item for item in employees}
    departments = {
        str(item.get("key")): str(item.get("name") or "Отдел")
        for item in config.get("departments", [])
    }
    entities = {
        str(item.get("key")): str(item.get("name") or "Компания")
        for item in config.get("legal_entities", [])
    }
    result: list[dict[str, Any]] = []
    for plan in config.get("plans", []):
        if str(plan.get("period") or "") != month:
            continue
        entity_key = str(plan.get("legal_entity_key") or "")
        if legal_entity != "all" and entity_key != legal_entity:
            continue
        scope_type = str(plan.get("scope_type") or "employee")
        scope_key = str(plan.get("scope_key") or plan.get("employee_key") or "")
        if scope_type == "employee":
            scoped_employees = (
                [employees_by_key[scope_key]] if scope_key in employees_by_key else []
            )
            scope_name = str((employees_by_key.get(scope_key) or {}).get("name") or "Сотрудник")
        elif scope_type == "department":
            scoped_employees = [
                item for item in employees
                if str(item.get("department_key") or "") == scope_key
            ]
            scope_name = departments.get(scope_key, "Отдел")
        else:
            scope_type = "company"
            scoped_employees = []
            scope_name = entities.get(entity_key, "Компания")

        deal_conditions = [
            Deal.legal_entity_key == entity_key,
            Deal.created_at.is_not(None),
            Deal.created_at >= start,
            Deal.created_at <= end,
        ]
        funnel_condition = _funnel_condition(funnel)
        if funnel_condition is not None:
            deal_conditions.append(funnel_condition)
        if scope_type != "company":
            deal_conditions.append(_employee_condition(scoped_employees))

        won_deals = int(await session.scalar(
            select(func.count()).select_from(Deal).where(
                *deal_conditions, Deal.status_class == "st-ok"
            )
        ) or 0)
        won_amount = int(await session.scalar(
            select(func.coalesce(func.sum(Deal.amount), 0)).where(
                *deal_conditions, Deal.status_class == "st-ok"
            )
        ) or 0)

        activity_conditions = [
            Deal.legal_entity_key == entity_key,
            CrmActivity.occurred_at.is_not(None),
            CrmActivity.occurred_at >= start,
            CrmActivity.occurred_at <= end,
        ]
        if funnel_condition is not None:
            activity_conditions.append(funnel_condition)
        if scope_type != "company":
            activity_conditions.append(_employee_condition(scoped_employees))
        activity_counts = dict((await session.execute(
            select(CrmActivity.kind, func.count(CrmActivity.id))
            .join(Deal, CrmActivity.deal_id == Deal.id)
            .where(*activity_conditions)
            .group_by(CrmActivity.kind)
        )).all())

        receipt_conditions = [
            OneCReceipt.excluded.is_(False),
            OneCReceipt.legal_entity_key == entity_key,
            OneCReceipt.registrar_date.is_not(None),
            OneCReceipt.registrar_date >= start,
            OneCReceipt.registrar_date <= end,
        ]
        receipt_stmt = select(
            func.count(OneCReceipt.id),
            func.coalesce(func.sum(OneCReceipt.amount), 0),
        )
        if scope_type != "company" or funnel_condition is not None:
            receipt_stmt = receipt_stmt.join(
                Deal, OneCReceipt.matched_deal_id == Deal.id
            )
            receipt_conditions.append(Deal.legal_entity_key == entity_key)
            if funnel_condition is not None:
                receipt_conditions.append(funnel_condition)
            if scope_type != "company":
                receipt_conditions.append(_employee_condition(scoped_employees))
        receipt_count, receipt_amount = (await session.execute(
            receipt_stmt.where(*receipt_conditions)
        )).one()
        if settings.onec_endpoint:
            payments, revenue = int(receipt_count or 0), float(receipt_amount or 0)
        else:
            payments, revenue = won_deals, float(won_amount)

        fact = {
            "revenue": revenue,
            "payments": payments,
            "deals": won_deals,
            "calls": int(activity_counts.get("call", 0)),
            "meetings": int(activity_counts.get("meeting", 0)),
        }
        targets = {metric: int(plan.get(metric) or 0) for metric in _METRICS}
        completion = {
            metric: _completion(targets[metric], fact[metric]) for metric in _METRICS
        }
        scored = [value for value in completion.values() if value is not None]
        result.append({
            "key": str(plan.get("key") or f"{scope_type}:{scope_key}:{month}"),
            "scope_type": scope_type,
            "scope_key": scope_key,
            "scope_name": scope_name,
            "legal_entity_key": entity_key,
            "legal_entity_name": entities.get(entity_key, entity_key),
            "month": month,
            "plan": targets,
            "fact": fact,
            "completion": completion,
            "overall_completion": round(sum(scored) / len(scored), 1) if scored else None,
        })
    return result
