"""Планировщик (worker) на APScheduler.

Регулярные джобы боевого режима:
  · сверка сделок с Битрикс24 — часто, лёгкая (страховка на случай, если событие
    портала не дошло или было проглочено дебаунсом);
  · выгрузка источников и пересчёт витрин — редко, тяжёлая (отчёты Директа и
    Метрики готовятся долго и упираются в лимиты API);
  · генерация AI-инсайтов — в ночном окне.

В демо-режиме джобы выгрузки — no-op: демо-данные статичны.
"""

from __future__ import annotations

import signal
import time

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("lawyer.worker")


def _sync_deals(full: bool) -> None:
    """Сверка сделок с Битрикс24 без выгрузки рекламных источников."""
    import asyncio

    from app.services import maintenance

    try:
        # Режим и доступы читаются из БД внутри sync_deals — переключение
        # источника данных в UI подхватывается без перезапуска воркера.
        result = asyncio.run(maintenance.sync_deals(full=full))
    except Exception as exc:  # noqa: BLE001 — джоба не должна ронять планировщик
        logger.error("Сверка сделок: ошибка %s", exc)
        return
    if result.get("skipped"):
        logger.info("Сверка сделок пропущена: %s", result.get("reason"))
    else:
        logger.info(
            "Сверка сделок: создано=%s обновлено=%s удалено=%s",
            result.get("created"), result.get("updated"), result.get("removed"),
        )


def reconcile_regulation() -> None:
    """Частая сверка сделок: подтягивает правки CRM, если событие портала не дошло.

    Нарушения регламента считаются на лету при каждом запросе, поэтому отдельно
    пересчитывать их не нужно — достаточно держать сделки свежими.
    """
    _sync_deals(full=False)


def ingest_sources() -> None:
    """Полная сверка сделок за окно дашборда.

    В отличие от частой сверки читает всё окно и убирает сделки, удалённые в
    портале, — их исчезновение события не порождает.
    """
    _sync_deals(full=True)


def recompute_analytics() -> None:
    """Ночной пересчёт сквозной аналитики и ROMI по методике (раздел 4 ТЗ).

    В боевом режиме выгружает источники и пересобирает витрины; в mock демо-данные
    статичны — пересчёт не требуется. Источник данных и доступы читаются из БД внутри
    ingest.main() (apply_overrides_from_db), поэтому переключение режима в UI
    подхватывается без перезапуска воркера.
    """
    try:
        import asyncio

        from app.services import ingest as ingest_mod

        asyncio.run(ingest_mod.main())
    except Exception as exc:  # noqa: BLE001
        logger.error("Ночной пересчёт аналитики: ошибка %s", exc)


def refresh_ai_insights() -> None:
    """Еженедельная генерация AI-инсайтов и рекомендаций по бюджету."""
    import asyncio

    from app.services import maintenance

    try:
        result = asyncio.run(maintenance.generate_ai())
    except Exception as exc:  # noqa: BLE001 — джоба не должна ронять планировщик
        logger.error("Генерация AI-инсайтов: ошибка %s", exc)
        return
    if result.get("generated"):
        logger.info(
            "AI-инсайты обновлены: инсайтов=%s рекомендаций=%s",
            result.get("insights", 0),
            result.get("budget_recs", 0),
        )
    else:
        logger.info("Генерация AI-инсайтов пропущена: %s", result.get("reason"))


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    # Сверка сделок — часто и дёшево: тянутся только изменённые сделки.
    scheduler.add_job(
        reconcile_regulation, "interval", minutes=5, id="reconcile_regulation",
        max_instances=1, coalesce=True,
    )
    # Полная сверка окна — реже: ловит удалённые в портале сделки.
    scheduler.add_job(
        ingest_sources, "interval", hours=1, id="ingest_sources",
        max_instances=1, coalesce=True,
    )
    # Ночной пересчёт выполняется ежедневно; агрегированный AI-разбор — раз в
    # неделю, как требует ТЗ, чтобы не вызывать модель на каждое событие.
    scheduler.add_job(recompute_analytics, "cron", hour=3, minute=0, id="recompute_analytics")
    scheduler.add_job(
        refresh_ai_insights,
        "cron",
        day_of_week="mon",
        hour=3,
        minute=30,
        id="refresh_ai_insights",
    )
    return scheduler


def _sync_settings_from_db() -> None:
    """Применяет сохранённые через UI доступы/режим к настройкам процесса."""
    try:
        import asyncio

        from app.core.db import SessionLocal
        from app.services.integrations_config import apply_overrides_from_db

        async def _run() -> None:
            async with SessionLocal() as session:
                await apply_overrides_from_db(session)

        asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — старт воркера не должен падать
        logger.warning("UI-настройки интеграций не применены: %s", exc)


def main() -> None:
    _sync_settings_from_db()
    logger.info("Старт worker :: env=%s data_source=%s", settings.app_env, settings.data_source)
    scheduler = build_scheduler()
    scheduler.start()

    stop = False

    def _shutdown(signum, frame):  # noqa: ANN001, ARG001
        nonlocal stop
        logger.info("Получен сигнал %s — останавливаю планировщик", signum)
        stop = True

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        while not stop:
            time.sleep(1)
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Worker остановлен")


if __name__ == "__main__":
    main()
