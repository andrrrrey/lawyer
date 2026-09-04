"""Роутер аутентификации: вход, выход, текущий пользователь."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, require_session
from app.core.config import settings
from app.core.db import get_session
from app.core.security import (
    SESSION_COOKIE,
    create_session_token,
    verify_credentials,
    verify_password,
)
from app.models import AppUser

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    login: str
    password: str


class UserResponse(BaseModel):
    login: str
    role: str
    employee_key: str = ""
    department_key: str = ""


@router.post("/login", response_model=UserResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    user: UserResponse | None = None
    if verify_credentials(payload.login, payload.password):
        user = UserResponse(login=payload.login, role="owner")
    else:
        row = (await session.execute(
            select(AppUser).where(
                AppUser.login == payload.login,
                AppUser.enabled.is_(True),
            )
        )).scalar_one_or_none()
        if row and verify_password(payload.password, row.password_hash):
            user = UserResponse(
                login=row.login,
                role=row.role,
                employee_key=row.employee_key,
                department_key=row.department_key,
            )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )
    token = create_session_token(
        user.login,
        role=user.role,
        employee_key=user.employee_key,
        department_key=user.department_key,
    )
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )
    return user


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
async def me(user: AuthUser = Depends(require_session)) -> UserResponse:
    return UserResponse(
        login=user.login,
        role=user.role,
        employee_key=user.employee_key,
        department_key=user.department_key,
    )
