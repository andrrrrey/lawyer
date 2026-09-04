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
    )


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
