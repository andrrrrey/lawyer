"""Общие фикстуры тестов: тестовая БД на SQLite + авторизованный клиент.

БД — временный файл SQLite (aiosqlite), NullPool исключает переиспользование
соединений между событийными циклами. Демо-данные загружаются штатным сид-скриптом.
"""

from __future__ import annotations

import asyncio
import pathlib
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 — регистрирует таблицы
from app.core.config import settings
from app.core.db import Base, get_session
from app.main import app
from app.seed import seed_all

DB_PATH = pathlib.Path(tempfile.gettempdir()) / "lawyer_test.db"


@pytest.fixture(scope="session")
def engine():
    if DB_PATH.exists():
        DB_PATH.unlink()
    eng = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", poolclass=NullPool)

    async def setup() -> None:
        settings.data_source = "mock"  # сид использует мок-адаптеры
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_maker = async_sessionmaker(eng, expire_on_commit=False)
        async with session_maker() as session:
            await seed_all(session)

    asyncio.run(setup())
    yield eng
    asyncio.run(eng.dispose())
    if DB_PATH.exists():
        DB_PATH.unlink()


@pytest.fixture(scope="session")
def session_maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(scope="session")
def client(engine, session_maker):
    async def override_get_session():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    # Данные уже загружены в тестовую БД; отключаем авто-сид на старте,
    # сохраняя DATA_SOURCE=mock (детерминированный MOCK_NOW для мониторинга).
    settings.data_source = "mock"
    import app.main as main_module

    async def _noop() -> None:
        return None

    main_module._autoseed_if_needed = _noop
    # Lifespan использует глобальный SessionLocal, а не dependency override.
    # Не читаем сохранённые production-доступы при изолированном API-тесте и не
    # позволяем им переключить settings.data_source с mock на real.
    main_module._apply_integration_overrides = _noop

    with TestClient(app) as c:
        resp = c.post("/api/auth/login", json={"login": "admin", "password": "admin"})
        assert resp.status_code == 200
        yield c

    app.dependency_overrides.clear()
