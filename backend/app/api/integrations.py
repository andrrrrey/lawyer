"""Роутер настроек интеграций: чтение/сохранение доступов и тест подключения.

Все эндпоинты защищены сессией. Секреты наружу отдаются замаскированными; тест
подключения делает реальный лёгкий запрос к API провайдера.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import require_owner
from app.core.config import settings
from app.core.db import get_session
from app.services import integrations_check as checker
from app.services import integrations_config as cfg
from app.services import maintenance

router = APIRouter(
    prefix="/integrations",
    tags=["integrations"],
    dependencies=[Depends(require_owner)],
)


class SaveRequest(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    clear: list[str] = Field(default_factory=list)
    data_source: str | None = None


class FieldMapRequest(BaseModel):
    fields: dict[str, str] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


@router.get("")
async def get_integrations(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Текущая конфигурация (секреты замаскированы) + режим источника данных."""
    return await cfg.get_config(session)


@router.put("")
async def put_integrations(
    payload: SaveRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Сохраняет доступы и (опционально) переключает источник данных."""
    if payload.data_source is not None and payload.data_source not in ("mock", "real"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="data_source должен быть 'mock' или 'real'",
        )
    return await cfg.save_config(
        session,
        values=payload.values,
        clear=payload.clear,
        data_source=payload.data_source,
    )


@router.get("/data-source")
async def get_data_source(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Текущий источник данных (mock|real) — из БД, единый для всех воркеров."""
    return {"data_source": await cfg.load_data_source(session)}


@router.put("/field-map")
async def put_field_map(
    payload: FieldMapRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Сохраняет сопоставление пользовательских полей Битрикс24."""
    return await cfg.save_field_map(session, payload.fields, payload.required)


@router.get("/bitrix/schema")
async def bitrix_schema(
    source: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Живая схема воронки Битрикс24: поля сделки и стадии (для настройки маппинга)."""
    await cfg.apply_overrides_from_db(session)

    def _load() -> dict[str, Any]:
        from app.integrations import factory
        connections = factory.get_bitrix24_connections()
        adapter = next(
            (item for key, item in connections if key == source),
            connections[0][1] if connections else factory.get_bitrix24(),
        )
        try:
            fields = adapter.fetch_deal_fields()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "fields": [], "stages": []}
        stages = []
        try:
            stages = adapter.fetch_stages()
        except Exception:  # noqa: BLE001 — стадии необязательны для маппинга полей
            pass
        return {"ok": True, "fields": fields, "stages": stages}

    return await run_in_threadpool(_load)


@router.get("/bitrix/funnels")
async def bitrix_funnels(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Воронки сделок из обоих настроенных порталов Bitrix24.

    Справочник доступен и в демонстрационном режиме: это позволяет сначала
    сохранить вебхуки и выбрать нужные воронки, а уже затем включить боевые данные.
    URL вебхуков и тексты сетевых исключений наружу не возвращаются.
    """
    await cfg.apply_overrides_from_db(session)

    def _load() -> dict[str, Any]:
        from app.integrations.real.bitrix24 import RealBitrix24Adapter

        connections = [
            ("box", "Коробочный Bitrix24", settings.bitrix_box_webhook_url),
            ("cloud", "Облачный Bitrix24", settings.bitrix_cloud_webhook_url),
        ]
        sources: list[dict[str, Any]] = []
        for key, name, webhook_url in connections:
            configured = bool((webhook_url or "").strip())
            item: dict[str, Any] = {
                "key": key,
                "name": name,
                "configured": configured,
                "ok": False,
                "funnels": [],
            }
            if not configured:
                item["error"] = "Сначала сохраните URL входящего вебхука в интеграциях."
            else:
                try:
                    item["funnels"] = RealBitrix24Adapter(
                        webhook_url=webhook_url, source_key=key
                    ).fetch_funnels()
                    item["ok"] = True
                except Exception:  # noqa: BLE001 — безопасное сообщение без URL/токена
                    item["error"] = (
                        "Не удалось получить воронки. Проверьте вебхук и право чтения CRM."
                    )
            sources.append(item)
        return {"sources": sources}

    return await run_in_threadpool(_load)


@router.get("/moysklad/schema")
async def moysklad_schema(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Структура Postgres-реплики `mpdb`: таблицы и колонки (для сопоставления)."""
    await cfg.apply_overrides_from_db(session)
    dsn = (settings.moysklad_pg_dsn or "").strip()
    if not dsn:
        return {"ok": False, "error": "DSN реплики (mpdb) не задан", "tables": []}

    def _load() -> dict[str, Any]:
        from app.integrations.real import _pg
        try:
            tables = _pg.introspect(dsn)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "tables": []}
        return {"ok": True, "tables": tables}

    return await run_in_threadpool(_load)


@router.post("/check")
async def check_all(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Проверяет подключение ко всем интеграциям сразу."""
    # Синхронизируем доступы из БД в этот воркер, чтобы проверка использовала
    # последние сохранённые значения (а не устаревшие из памяти другого воркера).
    await cfg.apply_overrides_from_db(session)
    results = await run_in_threadpool(checker.run_all_checks)
    for provider, result in results.items():
        await cfg.save_check_result(session, provider, result)
    return results


@router.post("/{provider}/check")
async def check_one(
    provider: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Проверяет подключение одной интеграции."""
    await cfg.apply_overrides_from_db(session)
    result = await run_in_threadpool(checker.run_check, provider)
    await cfg.save_check_result(session, provider, result)
    return result


# Пересчёт может идти минуты (выгрузка источников), поэтому запускается фоново,
# а прогресс/итог опрашиваются через /recompute/status.
_RECOMPUTE_STALE = timedelta(minutes=15)


@router.post("/recompute")
async def recompute(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Запускает фоновый пересчёт данных дашборда. Возвращает статус (running)."""
    current = await cfg.get_recompute_status(session)
    if current.get("state") == "running" and not _is_stale(current.get("started_at")):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пересчёт уже выполняется.",
        )
    # Помечаем запуск сразу (чтобы опрос статуса не застал «idle») и стартуем поток.
    await cfg.set_recompute_status(session, {
        "state": "running", "step": "Запуск…",
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "finished_at": None, "mode": None, "error": None, "sources": {}, "stats": {},
    })
    threading.Thread(target=maintenance.run_recompute_blocking, daemon=True).start()
    return await cfg.get_recompute_status(session)


@router.get("/recompute/status")
async def recompute_status(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Текущий статус пересчёта (для опроса со страницы)."""
    return await cfg.get_recompute_status(session)


def _is_stale(started_at: str | None) -> bool:
    if not started_at:
        return True
    try:
        started = datetime.fromisoformat(started_at)
    except (ValueError, TypeError):
        return True
    return datetime.now(UTC) - started > _RECOMPUTE_STALE


@router.post("/ai/generate")
async def ai_generate(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Запускает генерацию AI-инсайтов (только при подключённой AI-интеграции)."""
    await cfg.apply_overrides_from_db(session)
    conf = await cfg.get_config(session)
    if not conf.get("ai_configured"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI-интеграция не настроена (укажите API-ключ и Base URL LLM).",
        )
    try:
        result = await run_in_threadpool(maintenance.run_blocking, maintenance.generate_ai)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"LLM вернул некорректный ответ: {exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001 — сетевые ошибки LLM → 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка генерации: {exc}",
        ) from exc
    return result
