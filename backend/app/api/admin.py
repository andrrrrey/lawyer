"""Роутер админ-панели регламента: чтение, сохранение настроек и откат истории."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, require_owner
from app.core.config import settings as app_settings
from app.core.db import get_session
from app.core.security import hash_password
from app.models import AppUser, ExpenseArticle, ManualExpense, OneCReceipt
from app.services import admin, business_settings, content

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_owner)])


class AppUserPayload(BaseModel):
    login: str = Field(min_length=3, max_length=128)
    password: str = Field(default="", max_length=256)
    role: str = "manager"
    employee_key: str = Field(default="", max_length=128)
    department_key: str = Field(default="", max_length=128)
    enabled: bool = True

    @field_validator("login")
    @classmethod
    def valid_login(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Логин должен содержать не менее 3 символов")
        return value

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in {"owner", "head", "manager"}:
            raise ValueError("Неизвестная роль")
        return value


def _user_row(row: AppUser) -> dict[str, Any]:
    return {
        "id": row.id, "login": row.login, "role": row.role,
        "employee_key": row.employee_key, "department_key": row.department_key,
        "enabled": row.enabled,
    }


async def _validate_user_scope(payload: AppUserPayload, session: AsyncSession) -> None:
    if payload.login == app_settings.admin_login:
        raise HTTPException(status_code=409, detail="Этот логин занят основной учётной записью")
    config = await business_settings.get_settings(session)
    if payload.role == "manager" and payload.employee_key not in {
        str(item.get("key")) for item in config.get("employees", []) if item.get("enabled", True)
    }:
        raise HTTPException(status_code=422, detail="Для менеджера выберите активного сотрудника")
    if payload.role == "head" and payload.department_key not in {
        str(item.get("key")) for item in config.get("departments", []) if item.get("enabled", True)
    }:
        raise HTTPException(status_code=422, detail="Для руководителя выберите активный отдел")


@router.get("/users")
async def get_users(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    rows = (await session.execute(select(AppUser).order_by(AppUser.login))).scalars().all()
    return [_user_row(row) for row in rows]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AppUserPayload,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _validate_user_scope(payload, session)
    if len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="Пароль должен содержать не менее 8 символов")
    row = AppUser(
        login=payload.login, password_hash=hash_password(payload.password),
        role=payload.role, employee_key=payload.employee_key,
        department_key=payload.department_key, enabled=payload.enabled,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Такой логин уже существует") from exc
    await session.refresh(row)
    return _user_row(row)


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    payload: AppUserPayload,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _validate_user_scope(payload, session)
    row = await session.get(AppUser, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if payload.password and len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="Пароль должен содержать не менее 8 символов")
    row.login = payload.login
    row.role = payload.role
    row.employee_key = payload.employee_key
    row.department_key = payload.department_key
    row.enabled = payload.enabled
    if payload.password:
        row.password_hash = hash_password(payload.password)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Такой логин уже существует") from exc
    await session.refresh(row)
    return _user_row(row)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    result = await session.execute(delete(AppUser).where(AppUser.id == user_id))
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    await session.commit()
    return {"ok": True}


class ManualExpensePayload(BaseModel):
    spent_at: date
    legal_entity_key: str = Field(min_length=1, max_length=32)
    article: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    include_in_romi: bool = False
    channel: str = Field(default="", max_length=128)
    campaign: str = Field(default="", max_length=128)
    comment: str = Field(default="", max_length=500)


class ExpenseArticlePayload(BaseModel):
    legal_entity_key: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)


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
            detail="Для учёта расхода в ROMI укажите источник привлечения",
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


@router.get("/expense-articles")
async def get_expense_articles(
    legal_entity_key: str,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Справочник + ранее использованные статьи.

    Bitrix24 не имеет стандартного справочника расходов, а текущий endpoint 1С
    отдаёт поступления. Если 1С начнёт передавать расходные операции с
    operation=expense/outcome, они автоматически появятся в списке.
    """
    config = await business_settings.get_settings(session)
    entity_keys = {
        str(item.get("key")) for item in config.get("legal_entities", [])
        if item.get("enabled", True)
    }
    if legal_entity_key not in entity_keys:
        raise HTTPException(status_code=422, detail="Неизвестное юридическое лицо")

    result: dict[str, dict[str, Any]] = {}
    saved = (await session.execute(
        select(ExpenseArticle).where(
            ExpenseArticle.legal_entity_key == legal_entity_key
        ).order_by(ExpenseArticle.name)
    )).scalars().all()
    for row in saved:
        result[row.name.casefold()] = {
            "id": row.id, "name": row.name, "legal_entity_key": row.legal_entity_key,
            "source": "catalog", "source_label": "Справочник", "persisted": True,
        }

    historical = (await session.execute(
        select(ManualExpense.article).where(
            ManualExpense.legal_entity_key == legal_entity_key
        ).distinct().order_by(ManualExpense.article)
    )).scalars().all()
    for name in historical:
        clean = str(name or "").strip()
        if clean:
            result.setdefault(clean.casefold(), {
                "id": None, "name": clean, "legal_entity_key": legal_entity_key,
                "source": "history", "source_label": "Ранее использованные",
                "persisted": False,
            })

    one_c = (await session.execute(
        select(OneCReceipt.article_name).where(
            OneCReceipt.legal_entity_key == legal_entity_key,
            OneCReceipt.operation.in_(("expense", "outcome")),
        ).distinct().order_by(OneCReceipt.article_name)
    )).scalars().all()
    for name in one_c:
        clean = str(name or "").strip()
        if clean:
            result.setdefault(clean.casefold(), {
                "id": None, "name": clean, "legal_entity_key": legal_entity_key,
                "source": "onec", "source_label": "1С", "persisted": False,
            })
    return sorted(result.values(), key=lambda item: (item["source_label"], item["name"].casefold()))


@router.post("/expense-articles", status_code=status.HTTP_201_CREATED)
async def create_expense_article(
    payload: ExpenseArticlePayload,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    config = await business_settings.get_settings(session)
    entity_keys = {
        str(item.get("key")) for item in config.get("legal_entities", [])
        if item.get("enabled", True)
    }
    if payload.legal_entity_key not in entity_keys:
        raise HTTPException(status_code=422, detail="Неизвестное юридическое лицо")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Укажите наименование статьи")
    existing = (await session.execute(
        select(ExpenseArticle).where(
            ExpenseArticle.legal_entity_key == payload.legal_entity_key
        )
    )).scalars().all()
    if any(row.name.casefold() == name.casefold() for row in existing):
        raise HTTPException(status_code=409, detail="Такая статья уже есть в справочнике")
    row = ExpenseArticle(
        legal_entity_key=payload.legal_entity_key,
        name=name,
        source="manual",
        created_at=datetime.now(UTC),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Такая статья уже есть") from exc
    await session.refresh(row)
    return {
        "id": row.id, "name": row.name, "legal_entity_key": row.legal_entity_key,
        "source": "catalog", "source_label": "Справочник", "persisted": True,
    }


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
    subject: AuthUser = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await admin.update_regulation(session, data, user=subject.login)
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
    subject: AuthUser = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await admin.rollback(session, history_id, user=subject.login)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
