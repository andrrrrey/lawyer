"""Ручные операции обслуживания: пересчёт витрин и генерация AI.

Пересчёт запускается фоново (отдельный поток + свой event loop и движок БД),
а прогресс/итог пишутся в БД — так статус виден во всех воркерах и переживает
опрос со страницы. Генерация AI выполняется синхронно (один вызов LLM).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.logging import get_logger
from app.services import integrations_config as cfg

logger = get_logger("lawyer.maintenance")
_yandex_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def _with_session(fn: Callable[[AsyncSession], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    """Выполняет операцию с собственным движком/сессией (для фонового потока)."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            # Синхронизируем сохранённые через UI доступы/режим для этого процесса.
            await cfg.apply_overrides_from_db(session)
            return await fn(session)
    finally:
        await engine.dispose()


def run_blocking(coro_factory: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    """Запускает корутину в свежем event loop (вызывать из threadpool-потока)."""
    return asyncio.run(coro_factory())


# --------------------------- Генерация AI (синхронно) ---------------------------

async def _generate_ai(session: AsyncSession) -> dict[str, Any]:
    from app.services import ai_layer, deal_comments

    # Инсайты и рекомендации по бюджету — два независимых вызова LLM. Инсайты
    # коммитятся первыми: сбой генерации рекомендаций не должен откатывать их.
    comments = await deal_comments.generate_with_llm(session)
    insights = await ai_layer.generate_insights(session)
    result: dict[str, Any] = {
        "generated": bool(comments.get("generated") or insights.get("generated")),
        "insights": insights.get("count", 0),
        "deal_comments": comments.get("count", 0),
    }
    if not insights.get("generated"):
        result["reason"] = insights.get("reason")
    try:
        recs = await ai_layer.generate_budget_recs(session)
        result["budget_recs"] = recs.get("count", 0)
        result["generated"] = result["generated"] or bool(recs.get("generated"))
    except Exception as exc:  # noqa: BLE001 — не роняем успешные инсайты из-за рекомендаций
        logger.warning("Генерация рекомендаций по бюджету не удалась: %s", exc)
        result["budget_recs"] = 0
        result["budget_recs_error"] = str(exc)
    # Совместимость с UI: total-счётчик карточек (инсайты + рекомендации).
    result["count"] = result["insights"] + result["budget_recs"] + result["deal_comments"]
    return result


async def generate_ai() -> dict[str, Any]:
    """Генерация AI-инсайтов и рекомендаций по бюджету через LLM (если подключён LLM)."""
    return await _with_session(_generate_ai)


# ------------------ Сверка сделок (фоново, лёгкий путь) -------------------------

# Одна сверка за раз в процессе: события портала и тик планировщика не должны
# накладываться друг на друга и писать в одни и те же строки сделок.
_deals_lock = threading.Lock()


def run_deals_sync_blocking() -> None:
    """Точка входа фонового потока: быстрая сверка сделок с Битрикс24.

    Рекламные источники не трогаются — это отдельный (долгий) пересчёт.
    """
    if not _deals_lock.acquire(blocking=False):
        logger.info("Сверка сделок уже идёт — пропуск")
        return
    try:
        result = asyncio.run(sync_deals())
        if result.get("skipped"):
            logger.info("Сверка сделок пропущена: %s", result.get("reason"))
    except Exception:  # noqa: BLE001 — фоновый поток не должен ронять процесс
        logger.exception("Сверка сделок упала")
    finally:
        _deals_lock.release()


async def sync_deals(
    full: bool = False,
    *,
    source_keys: set[str] | None = None,
    entity_types: set[str] | None = None,
) -> dict[str, Any]:
    """Синхронизирует сделки из Битрикс24 (без выгрузки рекламных источников)."""
    from app.services import ingest as ingest_mod

    return await _with_session(lambda s: ingest_mod.refresh_deals(
        s,
        full=full,
        source_keys=source_keys,
        entity_types=entity_types,
    ))


def run_targeted_sync_blocking(
    *, source_keys: set[str], entity_types: set[str], full: bool = True
) -> None:
    """Целевая синхронизация выбранных CRM-сущностей с общим статусом в UI."""
    asyncio.run(_targeted_sync_job(
        source_keys=source_keys, entity_types=entity_types, full=full
    ))


async def _targeted_sync_job(
    *, source_keys: set[str], entity_types: set[str], full: bool
) -> None:
    label = ", ".join(
        f"{source}:{entity}"
        for source in sorted(source_keys)
        for entity in sorted(entity_types)
    )

    async def report(**patch: Any) -> None:
        await _with_session(lambda s: _save_targeted_status(s, patch))

    try:
        await report(
            state="running",
            step=f"Целевая синхронизация: {label}",
            started_at=_now(),
            finished_at=None,
            error=None,
        )
        result = await sync_deals(
            full=full, source_keys=source_keys, entity_types=entity_types
        )
        await report(
            state="done",
            step=f"Готово: {label}",
            finished_at=_now(),
            stats={"targeted_sync": result},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Целевая синхронизация %s упала", label)
        await report(
            state="error",
            step=f"Ошибка целевой синхронизации: {label}",
            finished_at=_now(),
            error=str(exc),
        )
        raise


async def _save_targeted_status(
    session: AsyncSession, patch: dict[str, Any]
) -> dict[str, Any]:
    await cfg.merge_recompute_status(session, patch)
    return patch


# --------------------------- Пересчёт (фоново, со статусом) ---------------------

def run_recompute_blocking() -> bool:
    """Точка входа фонового потока: выполняет пересчёт и пишет статус в БД."""
    return asyncio.run(_recompute_job())


async def _recompute_job() -> bool:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def report(**patch: Any) -> None:
        async with session_factory() as s:
            await cfg.merge_recompute_status(s, patch)

    try:
        async with session_factory() as s:
            await cfg.apply_overrides_from_db(s)

        await report(state="running", step="Подготовка…", started_at=_now(),
                     finished_at=None, error=None, mode=settings.data_source, sources={})

        async def progress(step: str) -> None:
            await report(step=step)

        if settings.data_source == "real":
            from app.services import ingest as ingest_mod
            async with session_factory() as s:
                await cfg.apply_overrides_from_db(s)
                result = await ingest_mod.ingest_all(s, progress=progress)
        else:
            from app import seed as seed_mod
            await progress("Пересбор демонстрационных данных…")
            async with session_factory() as s:
                await seed_mod.seed_all(s)
            result = {"mode": "mock", "sources": {"demo": {"status": "ok"}},
                      "stats": {"reseeded": True}}

        await report(state="done", step="Готово", finished_at=_now(),
                     mode=result.get("mode"), sources=result.get("sources", {}),
                     stats=result.get("stats", {}))
        logger.info("Пересчёт завершён: %s", result.get("stats"))
        return True
    except Exception as exc:  # noqa: BLE001 — фиксируем ошибку в статусе
        logger.exception("Пересчёт упал")
        try:
            await report(state="error", step="Ошибка", finished_at=_now(), error=str(exc))
        except Exception:  # noqa: BLE001
            pass
        return False
    finally:
        await engine.dispose()


# ----------------------- Отдельная синхронизация Яндекса ----------------------

def run_yandex_sync_blocking() -> bool:
    """Обновляет только Direct/Метрику; параллельные запуски отбрасываются."""
    if not _yandex_lock.acquire(blocking=False):
        logger.info("Синхронизация Яндекса уже выполняется — повторный запуск пропущен")
        return False
    try:
        return asyncio.run(_yandex_sync_job())
    finally:
        _yandex_lock.release()


async def _yandex_sync_job() -> bool:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def report(**patch: Any) -> None:
        async with session_factory() as session:
            await cfg.merge_yandex_sync_status(session, patch)

    try:
        await report(
            state="running", step="Подготовка подключений Яндекса…", started_at=_now(),
            finished_at=None, error=None, sources={}, stats={},
        )

        async def progress(step: str) -> None:
            await report(step=step)

        async with session_factory() as session:
            await cfg.apply_overrides_from_db(session)
            if settings.data_source != "real":
                result = {
                    "mode": settings.data_source,
                    "sources": {"yandex": {"status": "skipped"}},
                    "stats": {"reason": "Включён режим демонстрационных данных"},
                }
            else:
                from app.services.yandex_sync import sync_yandex
                result = await sync_yandex(session, progress=progress)
        await report(
            state="done", step="Данные Яндекса обновлены", finished_at=_now(),
            sources=result.get("sources", {}), stats=result.get("stats", {}),
        )
        logger.info("Синхронизация Яндекса завершена: %s", result.get("stats"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("Синхронизация Яндекса упала")
        try:
            await report(state="error", step="Ошибка", finished_at=_now(), error=str(exc))
        except Exception:  # noqa: BLE001
            pass
        return False
    finally:
        await engine.dispose()


# -------------------------- Отдельная синхронизация 1С -------------------------

def run_onec_sync_blocking() -> bool:
    return asyncio.run(_onec_sync_job())


async def _onec_sync_job() -> bool:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def report(**patch: Any) -> None:
        async with session_factory() as session:
            await cfg.merge_onec_sync_status(session, patch)

    try:
        await report(
            state="running", step="Загрузка поступлений 1С…", started_at=_now(),
            finished_at=None, error=None, sources={}, stats={},
        )
        async with session_factory() as session:
            await cfg.apply_overrides_from_db(session)
            if settings.data_source != "real":
                stats = {"skipped": True, "reason": "Демонстрационный режим"}
            elif not (settings.onec_endpoint and settings.onec_username and settings.onec_password):
                stats = {"skipped": True, "reason": "Подключение 1С не настроено"}
            else:
                from app.services.onec_sync import sync_onec
                stats = await sync_onec(session)
        await report(
            state="done", step="Поступления 1С обновлены", finished_at=_now(), stats=stats,
            sources={"onec": {"status": "skipped" if stats.get("skipped") else "ok",
                              "count": stats.get("rows")}},
        )
        logger.info("Синхронизация 1С завершена: %s", stats)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("Синхронизация 1С упала")
        try:
            await report(
                state="error", step="Ошибка", finished_at=_now(), error=str(exc),
                sources={"onec": {"status": "error", "message": str(exc)}},
            )
        except Exception:  # noqa: BLE001
            pass
        return False
    finally:
        await engine.dispose()
