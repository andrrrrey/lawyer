"""Общие зависимости FastAPI: защита эндпоинтов сессией."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.security import SESSION_COOKIE, decode_session_token
from app.models import AppUser


@dataclass(frozen=True)
class AuthUser:
    login: str
    role: str
    employee_key: str = ""
    department_key: str = ""
    scope_mode: str = "department"
    legal_entity_keys: tuple[str, ...] = ()


async def require_session(
    lawyer_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    session: AsyncSession = Depends(get_session),
) -> AuthUser:
    if not lawyer_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Не авторизовано")
    payload = decode_session_token(lawyer_session)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия недействительна",
        )
    login = str(payload["sub"])
    role = str(payload.get("role", "owner"))
    if role not in {"owner", "head", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Неизвестная роль")
    if role == "owner" and login == settings.admin_login:
        return AuthUser(login=login, role="owner")
    row = (await session.execute(
        select(AppUser).where(AppUser.login == login, AppUser.enabled.is_(True))
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Учётная запись отключена",
        )
    return AuthUser(
        login=row.login, role=row.role,
        employee_key=row.employee_key, department_key=row.department_key,
        scope_mode=row.scope_mode,
        legal_entity_keys=tuple(row.legal_entity_keys or []),
    )


async def scoped_manager(
    session: AsyncSession, user: AuthUser, requested: list[str] | None = None,
) -> str | list[str]:
    """Накладывает область сотрудника/отдела на выбранных менеджеров.

    Руководитель с доступом по юрлицам не ограничивается списком сотрудников:
    юридические лица ограничиваются отдельно функцией ``scoped_legal_entities``.
    """
    requested = requested or []
    if user.role == "owner" or (user.role == "head" and user.scope_mode == "legal_entities"):
        return requested or "all"
    from app.services import business_settings

    config = await business_settings.get_settings(session)
    if user.role == "head":
        names = [
            str(item.get("name") or "") for item in config.get("employees", [])
            if item.get("enabled", True)
            and str(item.get("department_key") or "") == user.department_key
            and item.get("name")
        ]
        if requested:
            selected = [name for name in requested if name in names]
            return selected or ["__no_access__"]
        return names or ["__no_access__"]
    employee = next(
        (item for item in config.get("employees", [])
         if str(item.get("key") or "") == user.employee_key),
        None,
    )
    return str(employee.get("name") or "") if employee else "__no_access__"


def scoped_legal_entities(user: AuthUser, requested: list[str]) -> str | list[str]:
    """Ограничивает запрос разрешёнными руководителю юридическими лицами."""
    if user.role != "head" or user.scope_mode != "legal_entities":
        return requested or "all"
    allowed = set(user.legal_entity_keys)
    if not allowed:
        return ["__no_access__"]
    if not requested:
        return sorted(allowed)
    selected = [key for key in requested if key in allowed]
    return selected or ["__no_access__"]


async def require_owner(user: AuthUser = Depends(require_session)) -> AuthUser:
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ только владельцу")
    return user


async def require_financial_access(user: AuthUser = Depends(require_session)) -> AuthUser:
    if user.role == "manager":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Финансовые данные скрыты",
        )
    return user
