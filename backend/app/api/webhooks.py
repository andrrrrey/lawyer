"""Приём входящих вебхуков Битрикс24.

Требования безопасности (раздел 7.2 ТЗ): вебхуки принимаются только по HTTPS
с проверкой секретного токена. Токен сверяется с BITRIX24_INBOUND_TOKEN и может
приходить в заголовке X-Webhook-Token, query-параметре token либо в поле формы
application_token (формат исходящих вебхуков Битрикс24).

В боевом режиме приход события (изменение сделки) запускает быструю сверку
сделок с порталом — с защитой от штормов: не чаще, чем раз в MIN_INTERVAL, и не
параллельно идущему полному пересчёту.

Сверка намеренно лёгкая: событие по сделке не требует перевыгрузки рекламных
источников (Директ/Метрика/МойСклад) — их отчёты готовятся минутами и упираются
в лимиты API. Полный пересчёт идёт по расписанию отдельно.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.logging import get_logger
from app.services import integrations_config as cfg
from app.services import maintenance

logger = get_logger("lawyer.webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Минимальный интервал между сверками по вебхуку (дебаунс всплесков). Сверка
# короткая, поэтому интервал небольшой — правки в CRM доезжают почти сразу.
_MIN_INTERVAL = timedelta(seconds=15)
_STALE = timedelta(minutes=15)

# Момент последней сверки в этом процессе (дебаунс без записи в БД: статус в БД
# принадлежит полному пересчёту, и лёгкая сверка не должна его перетирать).
_last_sync: datetime | None = None


async def _extract_token(request: Request) -> str | None:
    header = request.headers.get("X-Webhook-Token")
    if header:
        return header
    query = request.query_params.get("token")
    if query:
        return query
    ctype = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
        form = await request.form()
        return form.get("application_token") or form.get("auth[application_token]")
    return None


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


async def _maybe_trigger_sync(session: AsyncSession) -> bool:
    """Запускает фоновую сверку сделок, если можно (боевой режим, не чаще интервала)."""
    global _last_sync

    if await cfg.load_data_source(session) != "real":
        return False
    now = datetime.now(UTC)
    # Полный пересчёт уже идёт (и не завис) — он и так перечитает сделки.
    st = await cfg.get_recompute_status(session)
    started = _parse(st.get("started_at"))
    if st.get("state") == "running" and started and now - started < _STALE:
        return False
    # Дебаунс всплесков: при массовом изменении сделок хватит одной сверки.
    if _last_sync and now - _last_sync < _MIN_INTERVAL:
        return False
    _last_sync = now
    threading.Thread(target=maintenance.run_deals_sync_blocking, daemon=True).start()
    logger.info("Сверка сделок запущена по вебхуку Битрикс24")
    return True


@router.post("/bitrix24")
async def bitrix24_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    expected = settings.bitrix24_inbound_token
    token = await _extract_token(request)

    if expected:
        if not token or token != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный токен вебхука"
            )
    else:
        logger.warning("BITRIX24_INBOUND_TOKEN не задан — вебхук принят без проверки (dev)")

    triggered = False
    try:
        triggered = await _maybe_trigger_sync(session)
    except Exception as exc:  # noqa: BLE001 — ответ вебхуку не должен падать
        logger.warning("Сверка по вебхуку не запущена: %s", exc)

    logger.info("Вебхук Битрикс24 принят (сверка запущена: %s)", triggered)
    # recompute_triggered оставлен для совместимости с прежним контрактом ответа.
    return {
        "ok": True, "received": True,
        "sync_triggered": triggered, "recompute_triggered": triggered,
    }
