"""Роутер ROMI и рекомендаций: графики, рекомендации по бюджету, минус-слова."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, require_financial_access
from app.core.db import get_session
from app.models import BudgetRec, MinusWord
from app.services import analytics, content

router = APIRouter(prefix="/romi", tags=["romi"], dependencies=[Depends(require_financial_access)])


@router.get("/by-channel")
async def get_by_channel(
    period: str = "30",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await analytics.romi_channels_chart(session, period, legal_entity)


@router.get("/campaigns")
async def get_campaigns(
    period: str = "30",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await analytics.campaigns_bubble(session, period, legal_entity)


@router.get("/budget-recs")
async def get_budget_recs(
    period: str = "30", legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await content.budget_recs(session, period, legal_entity)


@router.get("/minus-words")
async def get_minus_words(
    period: str = "30", legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await analytics.minus_words(session, period, legal_entity)


@router.patch("/budget-recs/{rec_id}")
async def patch_budget_rec(
    rec_id: int, payload: dict = Body(...), session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_financial_access),
) -> dict[str, Any]:
    row = await session.get(BudgetRec, rec_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Рекомендация не найдена")
    action = str(payload.get("status") or "")
    if action not in {"new", "accepted", "deferred"}:
        raise HTTPException(status_code=422, detail="Неизвестный статус рекомендации")
    row.status = action
    row.acted_by = user.login
    row.acted_at = datetime.now(UTC)
    row.deferred_until = datetime.now(UTC) + timedelta(days=7) if action == "deferred" else None
    await session.commit()
    return {"id": row.id, "status": row.status, "deferred_until": row.deferred_until}


@router.patch("/minus-words/{word_id}")
async def patch_minus_word(
    word_id: int, payload: dict = Body(...), session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await session.get(MinusWord, word_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    action = str(payload.get("status") or "")
    if action not in {"new", "accepted", "rejected", "exported"}:
        raise HTTPException(status_code=422, detail="Неизвестный статус")
    row.status = action
    await session.commit()
    return {"id": row.id, "status": row.status}
