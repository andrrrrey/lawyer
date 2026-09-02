"""Единая точка расчёта нарушений регламента (используется мониторингом и триажем)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Deal
from app.services import business_settings, content, reglament
from app.services.clock import reference_now


async def evaluate_current(
    session: AsyncSession,
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
) -> dict:
    """Возвращает {'regular': [...], 'review': [...]} по текущим данным и настройкам.

    mgr/source — фильтры дашборда: сужают набор сделок до передачи в движок,
    чтобы счётчики триажа отвечали на выбор менеджера и источника."""
    stmt = select(Deal).options(selectinload(Deal.tasks)).order_by(Deal.position)
    if mgr and mgr != "all":
        stmt = stmt.where(Deal.mgr == mgr)
    if source and source != "all":
        stmt = stmt.where(Deal.src == source)
    if legal_entity and legal_entity != "all":
        stmt = stmt.where(Deal.legal_entity_key == legal_entity)
    deals = (await session.execute(stmt)).scalars().all()
    config = await content.regulation(session)
    business_config = await business_settings.get_settings(session)
    # Сопоставление пользовательских полей Битрикс — только для движка (не в админку).
    from app.services.integrations_config import get_field_map
    config = {**config, "field_map": await get_field_map(session)}
    grouped: dict[str, tuple[dict | None, list[Deal]]] = {}
    for deal in deals:
        profile = business_settings.sla_profile_for_funnel(
            business_config, deal.crm_source, deal.funnel_id
        )
        key = str((profile or {}).get("key") or "legacy")
        grouped.setdefault(key, (profile, []))[1].append(deal)
    result = {"regular": [], "review": []}
    for profile, profile_deals in grouped.values():
        evaluated = reglament.evaluate(
            profile_deals,
            {**config, "sla_profile": profile or {}},
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
