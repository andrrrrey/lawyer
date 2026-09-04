"""Роутер AI-инсайтов."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_financial_access
from app.core.db import get_session
from app.services import content

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(require_financial_access)])


@router.get("/insights")
async def get_insights(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    return await content.insights(session)
