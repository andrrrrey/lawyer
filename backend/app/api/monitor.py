"""Роутер мониторинга Битрикс24: статистика, нарушения, оценочные на ревью."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, require_session
from app.core.db import get_session
from app.services import business_settings, monitor

router = APIRouter(prefix="/monitor", tags=["monitor"], dependencies=[Depends(require_session)])


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
    session: AsyncSession = Depends(get_session), user: AuthUser = Depends(require_session),
) -> dict[str, Any]:
    return await monitor.stats(session, await _manager_scope(session, user), user.role == "manager")


@router.get("/violations")
async def get_violations(
    ptype: str | None = None, session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_session),
) -> list[dict[str, Any]]:
    return await monitor.violations(
        session, ptype=ptype, mgr=await _manager_scope(session, user),
        hide_financial=user.role == "manager",
    )


@router.get("/review")
async def get_review(
    session: AsyncSession = Depends(get_session), user: AuthUser = Depends(require_session),
) -> list[dict[str, Any]]:
    return await monitor.review(
        session, mgr=await _manager_scope(session, user), hide_financial=user.role == "manager"
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
