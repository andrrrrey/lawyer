"""Роутер мониторинга Битрикс24: статистика, нарушения, оценочные на ревью."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_session
from app.core.db import get_session
from app.services import monitor

router = APIRouter(prefix="/monitor", tags=["monitor"], dependencies=[Depends(require_session)])


@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await monitor.stats(session)


@router.get("/violations")
async def get_violations(
    ptype: str | None = None, session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    return await monitor.violations(session, ptype=ptype)


@router.get("/review")
async def get_review(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    return await monitor.review(session)


@router.post("/task")
async def post_task(
    payload: dict = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await monitor.create_task_for(
            session, ref=payload.get("ref"), deal_key=payload.get("deal_key")
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — отказ Битрикс24/сети → 502 с причиной
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не удалось создать задачу в Битрикс24: {exc}",
        ) from exc
