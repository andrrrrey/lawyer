"""Роутер сквозной аналитики: цепочка «реклама→выручка» и каналы/кампании."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, require_financial_access, scoped_legal_entities
from app.core.db import get_session
from app.services import analytics

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_financial_access)],
)


@router.get("/chain")
async def get_chain(
    period: str = "30",
    legal_entity: list[str] = Query(default=[]),
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_financial_access),
) -> list[dict[str, Any]]:
    return await analytics.chain(
        session, period, legal_entity=scoped_legal_entities(user, legal_entity)
    )


@router.get("/channels")
async def get_channels(
    channel: str = "all",
    period: str = "30",
    legal_entity: list[str] = Query(default=[]),
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_financial_access),
) -> list[dict[str, Any]]:
    return await analytics.channels_table(
        session, channel=channel, period=period,
        legal_entity=scoped_legal_entities(user, legal_entity),
    )


@router.get("/reconciliation")
async def get_reconciliation(
    period: str = "30",
    legal_entity: list[str] = Query(default=[]),
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_financial_access),
) -> dict[str, Any]:
    return await analytics.reconciliation(
        session, period=period, legal_entity=scoped_legal_entities(user, legal_entity)
    )
