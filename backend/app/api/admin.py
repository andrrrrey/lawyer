"""Роутер админ-панели регламента: чтение, сохранение настроек и откат истории."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_session
from app.core.db import get_session
from app.models import OneCReceipt
from app.services import admin, business_settings, content

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_session)])


@router.get("/business-settings")
async def get_business_settings(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Настройки трёх юрлиц, воронок, SLA, сотрудников и планов."""
    return await business_settings.get_settings(session)


@router.put("/business-settings")
async def put_business_settings(
    data: dict = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await business_settings.save_settings(session, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/one-c/receipts")
async def get_one_c_receipts(
    state: str = "all",
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Безопасный журнал сопоставления поступлений 1С без исходного raw JSON."""
    stmt = select(OneCReceipt)
    if state == "excluded":
        stmt = stmt.where(OneCReceipt.excluded.is_(True))
    elif state == "unmatched":
        stmt = stmt.where(
            OneCReceipt.excluded.is_(False), OneCReceipt.matched_deal_id.is_(None)
        )
    elif state == "included":
        stmt = stmt.where(
            OneCReceipt.excluded.is_(False), OneCReceipt.matched_deal_id.is_not(None)
        )
    rows = (
        await session.execute(
            stmt.order_by(OneCReceipt.registrar_date.desc()).limit(min(max(limit, 1), 1000))
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "date": row.registrar_date.isoformat() if row.registrar_date else None,
            "number": row.registrar_number,
            "legal_entity_key": row.legal_entity_key,
            "organization": row.organization_name,
            "counterparty": row.counterparty_name,
            "article": row.article_name,
            "operation": row.operation,
            "amount": float(row.amount),
            "crm_external_id": row.crm_external_id,
            "matched": row.matched_deal_id is not None,
            "excluded": row.excluded,
            "reason": row.exclusion_reason,
        }
        for row in rows
    ]


@router.get("/regulation")
async def get_regulation(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    return await content.regulation(session)


@router.put("/regulation")
async def put_regulation(
    data: dict = Body(...),
    subject: str = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await admin.update_regulation(session, data, user=subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/history")
async def get_history(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    return await content.history(session)


@router.post("/history/{history_id}/rollback")
async def rollback_history(
    history_id: int,
    subject: str = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await admin.rollback(session, history_id, user=subject)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
