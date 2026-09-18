"""Роутер мониторинга Битрикс24: статистика, нарушения, оценочные на ревью."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, require_session
from app.core.db import get_session
from app.services import business_settings, monitor

router = APIRouter(prefix="/monitor", tags=["monitor"], dependencies=[Depends(require_session)])


def _multi(values: list[str]) -> str | list[str]:
    return values or "all"


async def _manager_scope(session: AsyncSession, user: AuthUser) -> str | list[str]:
    if user.role == "owner":
        return "all"
    config = await business_settings.get_settings(session)
    if user.role == "head":
        names = [
            str(item.get("name") or "") for item in config.get("employees", [])
            if item.get("enabled", True)
            and str(item.get("department_key") or "") == user.department_key
            and item.get("name")
        ]
        return names or ["__no_access__"]
    employee = next(
        (item for item in config.get("employees", [])
         if item.get("key") == user.employee_key),
        None,
    )
    return str(employee.get("name") or "") if employee else "__no_access__"


@router.get("/stats")
async def get_stats(
    legal_entity: list[str] = Query(default=[]),
    funnel: list[str] = Query(default=[]),
    session: AsyncSession = Depends(get_session), user: AuthUser = Depends(require_session),
) -> dict[str, Any]:
    return await monitor.stats(
        session, await _manager_scope(session, user), user.role == "manager",
        legal_entity=_multi(legal_entity), funnel=_multi(funnel),
    )


@router.get("/violations")
async def get_violations(
    ptype: str | None = None, date_from: date | None = None, date_to: date | None = None,
    legal_entity: list[str] = Query(default=[]), funnel: list[str] = Query(default=[]),
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_session),
) -> list[dict[str, Any]]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Дата начала не может быть позже даты окончания",
        )
    return await monitor.violations(
        session, ptype=ptype, mgr=await _manager_scope(session, user),
        hide_financial=user.role == "manager", date_from=date_from, date_to=date_to,
        legal_entity=_multi(legal_entity), funnel=_multi(funnel),
    )


@router.get("/review")
async def get_review(
    legal_entity: list[str] = Query(default=[]),
    funnel: list[str] = Query(default=[]),
    session: AsyncSession = Depends(get_session), user: AuthUser = Depends(require_session),
) -> list[dict[str, Any]]:
    return await monitor.review(
        session, mgr=await _manager_scope(session, user), hide_financial=user.role == "manager",
        legal_entity=_multi(legal_entity), funnel=_multi(funnel),
    )


@router.post("/task")
async def post_task(
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_session),
) -> dict[str, Any]:
    try:
        return await monitor.create_task_for(
            session, ref=payload.get("ref"), deal_key=payload.get("deal_key"),
            mgr=await _manager_scope(session, user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — отказ Битрикс24/сети → 502 с причиной
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не удалось создать задачу в Битрикс24: {exc}",
        ) from exc
