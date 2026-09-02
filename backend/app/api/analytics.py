"""Роутер сквозной аналитики: цепочка «реклама→маржа» и таблица каналов/кампаний."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_session
from app.core.db import get_session
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_session)])


@router.get("/chain")
async def get_chain(
    period: str = "30",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await analytics.chain(session, period, legal_entity=legal_entity)


@router.get("/channels")
async def get_channels(
    channel: str = "all",
    period: str = "30",
    legal_entity: str = "all",
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await analytics.channels_table(
        session, channel=channel, period=period, legal_entity=legal_entity
    )
