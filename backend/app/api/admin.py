"""Роутер админ-панели регламента: чтение, сохранение настроек и откат истории."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_session
from app.core.db import get_session
from app.models import ManualExpense, OneCReceipt
from app.services import admin, business_settings, content

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_session)])


class ManualExpensePayload(BaseModel):
    spent_at: date
    legal_entity_key: str = Field(min_length=1, max_length=32)
    article: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    include_in_romi: bool = False
    channel: str = Field(default="", max_length=128)
    campaign: str = Field(default="", max_length=128)
    comment: str = Field(default="", max_length=500)


def _expense_row(row: ManualExpense) -> dict[str, Any]:
    return {
        "id": row.id,
        "spent_at": row.spent_at.date().isoformat(),
        "legal_entity_key": row.legal_entity_key,
        "article": row.article,
        "amount": float(row.amount),
        "include_in_romi": row.include_in_romi,
        "channel": row.channel,
        "campaign": row.campaign,
        "comment": row.comment,
    }


async def _validated_expense_values(
    payload: ManualExpensePayload, session: AsyncSession
) -> dict[str, Any]:
    configured = await business_settings.get_settings(session)
    entity_keys = {
        str(item.get("key"))
        for item in configured.get("legal_entities", [])
        if item.get("enabled", True)
    }
    if payload.legal_entity_key not in entity_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Выбрано неизвестное или отключённое юридическое лицо",
        )
    article = payload.article.strip()
    channel = payload.channel.strip()
    if payload.include_in_romi and not channel:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Для учёта расхода в ROMI укажите рекламный канал",
        )
    return {
        "spent_at": datetime.combine(payload.spent_at, time.min, tzinfo=UTC),
        "legal_entity_key": payload.legal_entity_key,
        "article": article,
        "amount": payload.amount,
        "include_in_romi": payload.include_in_romi,
        "channel": channel,
        "campaign": payload.campaign.strip(),
        "comment": payload.comment.strip(),
    }


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


@router.get("/expenses")
async def get_manual_expenses(
    limit: int = 500,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(ManualExpense)
            .order_by(ManualExpense.spent_at.desc(), ManualExpense.id.desc())
            .limit(min(max(limit, 1), 2000))
        )
    ).scalars().all()
    return [_expense_row(row) for row in rows]


@router.post("/expenses", status_code=status.HTTP_201_CREATED)
async def create_manual_expense(
    payload: ManualExpensePayload,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    values = await _validated_expense_values(payload, session)
    row = ManualExpense(**values, created_at=datetime.now(UTC))
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _expense_row(row)


@router.put("/expenses/{expense_id}")
async def update_manual_expense(
    expense_id: int,
    payload: ManualExpensePayload,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await session.get(ManualExpense, expense_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Расход не найден")
    for key, value in (await _validated_expense_values(payload, session)).items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return _expense_row(row)


@router.delete("/expenses/{expense_id}")
async def delete_manual_expense(
    expense_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    result = await session.execute(
        delete(ManualExpense).where(ManualExpense.id == expense_id)
    )
    if not result.rowcount:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Расход не найден")
    await session.commit()
    return {"ok": True}


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
