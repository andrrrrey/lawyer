"""Точка входа FastAPI. Все API — под префиксом /api."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import (
    admin,
    ai,
    analytics,
    auth,
    dashboard,
    health,
    integrations,
    monitor,
    romi,
    webhooks,
)
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import get_logger

logger = get_logger("lawyer.api")


async def _autoseed_if_needed() -> None:
    """В mock-режиме наполняет пустую БД демо-данными при старте."""
    if settings.data_source != "mock":
        return
    from app.seed import is_empty, seed_all

    try:
        async with SessionLocal() as session:
            # Gunicorn запускает несколько процессов одновременно. В PostgreSQL
            # транзакционная advisory-блокировка не даёт им параллельно заполнить
            # одну и ту же пустую БД и получить конфликт первичных ключей.
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                await session.execute(text("SELECT pg_advisory_xact_lock(12021988)"))
            if await is_empty(session):
                logger.info("БД пуста — загружаю демо-данные (DATA_SOURCE=mock)")
                await seed_all(session)
    except Exception as exc:  # noqa: BLE001 — старт не должен падать из-за сида
        logger.warning("Авто-сид пропущен: %s", exc)


async def _apply_integration_overrides() -> None:
    """Накатывает сохранённые через UI доступы поверх переменных окружения."""
    from app.services.integrations_config import apply_overrides_from_db

    try:
        async with SessionLocal() as session:
            count = await apply_overrides_from_db(session)
            if count:
                logger.info("Применены UI-настройки интеграций: полей=%d", count)
    except Exception as exc:  # noqa: BLE001 — старт не должен падать из-за настроек
        logger.warning("UI-настройки интеграций не применены: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Запуск API :: env=%s data_source=%s", settings.app_env, settings.data_source)
    await _apply_integration_overrides()
    await _autoseed_if_needed()
    yield
    logger.info("Остановка API")


app = FastAPI(
    title="Lawyer API",
    description="AI-система контроля лидов и маркетинговой аналитики",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# CORS: в проде фронтенд и API за одним nginx (same-origin);
# для локальной разработки допускаем vite dev-сервер.
_dev_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.public_url, *_dev_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_prefix = "/api"
app.include_router(health.router, prefix=api_prefix)
app.include_router(auth.router, prefix=api_prefix)
app.include_router(dashboard.router, prefix=api_prefix)
app.include_router(monitor.router, prefix=api_prefix)
app.include_router(analytics.router, prefix=api_prefix)
app.include_router(romi.router, prefix=api_prefix)
app.include_router(ai.router, prefix=api_prefix)
app.include_router(admin.router, prefix=api_prefix)
app.include_router(integrations.router, prefix=api_prefix)
app.include_router(webhooks.router, prefix=api_prefix)
