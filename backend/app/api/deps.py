"""Общие зависимости FastAPI: защита эндпоинтов сессией."""

from __future__ import annotations

from fastapi import Cookie, HTTPException, status

from app.core.security import SESSION_COOKIE, decode_session_token


async def require_session(
    lawyer_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> str:
    """Пропускает запрос только при валидной сессии. Возвращает субъект (логин)."""
    if not lawyer_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Не авторизовано")
    payload = decode_session_token(lawyer_session)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия недействительна",
        )
    return str(payload["sub"])
