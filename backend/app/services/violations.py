"""Единая точка расчёта нарушений регламента (используется мониторингом и триажем)."""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import Deal
from app.services import business_settings, content, reglament
from app.services.clock import reference_now

FilterValue = str | list[str]
_CACHE_TTL_SECONDS = 30.0
_evaluation_cache: dict[tuple, tuple[float, dict]] = {}
_evaluation_locks: dict[tuple, asyncio.Lock] = {}


def invalidate_cache() -> None:
    """Сбрасывает витрину после изменения данных или настроек регламента."""
    _evaluation_cache.clear()


def _values(value: FilterValue) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if item and item != "all"]
    return [] if not value or value == "all" else [value]


async def evaluate_current(
    session: AsyncSession,
    mgr: str | list[str] = "all",
    source: str = "all",
    legal_entity: FilterValue = "all",
    funnel: FilterValue = "all",
) -> dict:
    """Кэширует одинаковый расчёт, который дашборд запрашивает несколькими блоками."""
    if settings.data_source == "mock":
        return await _evaluate_current_uncached(
            session, mgr=mgr, source=source,
            legal_entity=legal_entity, funnel=funnel,
        )
    key = (
        id(session.bind.sync_engine) if session.bind is not None else id(session),
        tuple(sorted(_values(mgr))),
        source or "all",
        tuple(sorted(_values(legal_entity))),
        tuple(sorted(_values(funnel))),
    )
    now = time.monotonic()
    cached = _evaluation_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]
    lock = _evaluation_locks.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _evaluation_cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        result = await _evaluate_current_uncached(
            session, mgr=mgr, source=source,
            legal_entity=legal_entity, funnel=funnel,
        )
        if len(_evaluation_cache) >= 128:
            _evaluation_cache.clear()
        _evaluation_cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, result)
        return result


async def _evaluate_current_uncached(
    session: AsyncSession,
    mgr: str | list[str] = "all",
    source: str = "all",
    legal_entity: FilterValue = "all",
    funnel: FilterValue = "all",
) -> dict:
    """Возвращает {'regular': [...], 'review': [...]} по текущим данным и настройкам.

    mgr/source — фильтры дашборда: сужают набор сделок до передачи в движок,
    чтобы счётчики триажа отвечали на выбор менеджера и источника."""
    # Успешно закрытые сделки движок регламента сразу пропускает: для них не
    # рассчитываются ни текущие нарушения, ни случаи «отказ/спам на проверке».
    # Не загружаем их вместе с задачами из БД — на больших порталах это заметно
    # сокращает первый (ещё не кэшированный) расчёт дашборда.
    stmt = (
        select(Deal)
        .where(Deal.status_class != "st-ok")
        .options(selectinload(Deal.tasks), selectinload(Deal.activities))
        .order_by(Deal.position)
    )
    manager_values = _values(mgr)
    if manager_values:
        stmt = stmt.where(Deal.mgr.in_(manager_values))
    if source and source != "all":
        stmt = stmt.where(Deal.src == source)
    legal_values = _values(legal_entity)
    if legal_values:
        stmt = stmt.where(Deal.legal_entity_key.in_(legal_values))
    funnel_clauses = []
    for value in _values(funnel):
        crm_source, separator, funnel_id = value.partition(":")
        if separator and crm_source and funnel_id:
            funnel_clauses.append(and_(
                Deal.crm_source == crm_source,
                Deal.funnel_id == funnel_id,
            ))
    if funnel_clauses:
        stmt = stmt.where(or_(*funnel_clauses))
    deals = (await session.execute(stmt)).scalars().all()
    config = await content.regulation(session)
    business_config = await business_settings.get_settings(session)
    deals = [
        deal for deal in deals
        if not business_settings.stage_is_successful(
            business_config, deal.crm_source, deal.funnel_id, deal.stage,
        )
    ]
    # Сопоставление пользовательских полей Битрикс — только для движка (не в админку).
    from app.services.integrations_config import get_field_map
    field_maps = {
        source: await get_field_map(session, source)
        for source in {deal.crm_source for deal in deals}
    }
    grouped: dict[str, tuple[dict | None, list[Deal]]] = {}
    for deal in deals:
        profile = business_settings.sla_profile_for_funnel(
            business_config, deal.crm_source, deal.funnel_id
        )
        key = f"{deal.crm_source}:{(profile or {}).get('key') or 'legacy'}"
        grouped.setdefault(key, (profile, []))[1].append(deal)
    result = {"regular": [], "review": []}
    for profile, profile_deals in grouped.values():
        source = profile_deals[0].crm_source
        evaluated = reglament.evaluate(
            profile_deals,
            {**config, "sla_profile": profile or {}, "field_map": field_maps.get(source, {})},
            reference_now(),
        )
        result["regular"].extend(evaluated["regular"])
        result["review"].extend(evaluated["review"])
    return result


# Порог «выброса» по умолчанию: сделки с суммой выше не учитываются в «деньгах под
# риском» — обычно это ошибки ввода в CRM (напр. лишние нули), которые иначе в разы
# завышают итог. Настраивается в конфиге регламента: evaluative.risk_amount_cap
# (0 — фильтр выключен).
RISK_AMOUNT_CAP_DEFAULT = 100_000_000  # ₽


def money_at_risk(regular: list[dict], cap: int | None = None) -> int:
    """Сумма сделок «под риском» — каждая сделка учитывается один раз.

    У одной сделки может быть несколько нарушений (нет задачи + нет движения + …);
    без дедупликации её сумма складывалась бы кратно числу нарушений, завышая итог.
    Ключ дедупа — ссылка на сделку (ref); при её отсутствии — имя из нарушения.

    cap — порог выброса (₽): сделки с суммой выше не учитываются. None → значение по
    умолчанию, 0 → фильтр выключен (учитываются все суммы).
    """
    limit = RISK_AMOUNT_CAP_DEFAULT if cap is None else cap
    by_deal: dict[str, int] = {}
    for v in regular:
        if v.get("severity") != "over":
            continue
        amount = int(v.get("amount") or 0)
        if limit and amount > limit:
            continue  # аномально большая сумма — вероятно мусор в CRM
        key = v.get("ref") or v.get("name") or id(v)
        by_deal[str(key)] = amount
    return sum(by_deal.values())


async def risk_amount_cap(session: AsyncSession) -> int:
    """Порог выброса из конфига регламента (evaluative.risk_amount_cap), ₽."""
    cfg = await content.regulation(session)
    raw = (cfg.get("evaluative") or {}).get("risk_amount_cap")
    try:
        cap = int(raw)
    except (TypeError, ValueError):
        return RISK_AMOUNT_CAP_DEFAULT
    return cap if cap >= 0 else RISK_AMOUNT_CAP_DEFAULT
