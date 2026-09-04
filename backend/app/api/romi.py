"""Роутер ROMI и рекомендаций: графики, рекомендации по бюджету, минус-слова."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_financial_access
from app.core.db import get_session
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
async def get_budget_recs(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    return await content.budget_recs(session)


@router.get("/minus-words")
async def get_minus_words(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await analytics.minus_words(session)
