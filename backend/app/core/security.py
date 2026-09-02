"""Аутентификация: единый вход (логин/пароль) + сессия на JWT (httpOnly-cookie).

В объёме Этапа 1 разграничение прав между пользователями не предусмотрено
(п.16 ТЗ): одна учётная запись администратора из переменных окружения.
Роли — кандидат в Этап 2.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings

ALGORITHM = "HS256"
SESSION_COOKIE = "lawyer_session"


def verify_credentials(login: str, password: str) -> bool:
    """Проверка логина/пароля с защитой от тайминг-атак."""
    login_ok = secrets.compare_digest(login, settings.admin_login)
    password_ok = secrets.compare_digest(password, settings.admin_password)
    return login_ok and password_ok


def create_session_token(subject: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.session_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.session_secret, algorithm=ALGORITHM)


def decode_session_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.session_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
