"""Показатели дашборда: KPI, воронка, источники, таймсерии, ROMI, триаж, менеджеры, лиды."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    AdCost,
    Baseline,
    Channel,
    Deal,
    KpiCard,
    ManagerControl,
    ManualExpense,
    OneCReceipt,
    StageHistory,
    Visit,
)
from app.services import format as f
from app.services import period as per
from app.services import romi as romi_svc


def _period_start(period: str | None, now: datetime) -> datetime:
    return per.start(period, now)


def _period_end(period: str | None, now: datetime) -> datetime | None:
    """Верхняя граница периода (исключающая); None у открытых пресетов."""
    return per.end(period, now)


def _by_deal_filters(
    stmt, mgr: str = "all", source: str = "all", legal_entity: str = "all",
    funnel: str = "all",
):
    """Единые фильтры дашборда на выборку сделок."""
    if mgr and mgr != "all":
        stmt = stmt.where(Deal.mgr == mgr)
    if source and source != "all":
        stmt = stmt.where(Deal.src == source)
    if legal_entity and legal_entity != "all":
        stmt = stmt.where(Deal.legal_entity_key == legal_entity)
    if funnel and funnel != "all":
        crm_source, separator, funnel_id = funnel.partition(":")
        if separator and crm_source and funnel_id:
            stmt = stmt.where(
                Deal.crm_source == crm_source,
                Deal.funnel_id == funnel_id,
            )
    return stmt


async def _ad_totals(
    session: AsyncSession, period: str, legal_entity: str = "all"
) -> dict[str, float]:
    """Расход/клики (Директ) и визиты (Метрика) за период из посуточного сырья.

    Рекламные показатели не разрезаются фильтрами «менеджер»/«источник»: расход
    относится к кампании, а не к ответственному, а таксономия источников Метрики
    не совпадает с SOURCE_ID Битрикс24 — смешивать их было бы неверно.

    Пока посуточного сырья нет (пересчёт не выполнялся после обновления), берём
    сохранённые итоги последнего пересчёта — иначе показатели обнулились бы.
    """
    now = datetime.now(UTC)
    start = _period_start(period, now)
    end = _period_end(period, now)
    cost_where = [AdCost.date.is_not(None), AdCost.date >= start]
    visit_where = [Visit.date.is_not(None), Visit.date >= start]
    if end is not None:
        cost_where.append(AdCost.date < end)
        visit_where.append(Visit.date < end)
    if legal_entity and legal_entity != "all":
        cost_where.append(AdCost.legal_entity_key == legal_entity)
        visit_where.append(Visit.legal_entity_key == legal_entity)
    manual_where = [
        ManualExpense.include_in_romi.is_(True),
        ManualExpense.spent_at >= start,
    ]
    if end is not None:
        manual_where.append(ManualExpense.spent_at < end)
    if legal_entity and legal_entity != "all":
        manual_where.append(ManualExpense.legal_entity_key == legal_entity)
    spend, clicks = (await session.execute(
        select(
            func.coalesce(func.sum(AdCost.spend), 0),
            func.coalesce(func.sum(AdCost.clicks), 0),
        ).where(*cost_where)
    )).one()
    visits = (await session.execute(
        select(func.coalesce(func.sum(Visit.visits), 0)).where(*visit_where)
    )).scalar() or 0
    manual_spend = (await session.execute(
        select(func.coalesce(func.sum(ManualExpense.amount), 0)).where(*manual_where)
    )).scalar() or 0

    has_direct_costs = bool(await session.scalar(select(func.count()).select_from(AdCost)))
    has_manual_costs = bool(await session.scalar(
        select(func.count()).select_from(ManualExpense).where(
            ManualExpense.include_in_romi.is_(True)
        )
    ))
    has_costs = has_direct_costs or has_manual_costs
    has_visits = bool(await session.scalar(select(func.count()).select_from(Visit)))
    if has_costs and has_visits:
        return {
            "spend": float(spend + manual_spend),
            "clicks": float(clicks),
            "visits": float(visits),
        }

    # Резерв на данных прошлых версий: итоги каналов и базлайна за всё окно.
    legacy_spend = int((await session.execute(
        select(func.coalesce(func.sum(Channel.spend), 0))
    )).scalar() or 0)
    legacy = dict((await session.execute(
        select(Baseline.key, Baseline.value).where(Baseline.key.in_(["clicks", "visits"]))
    )).all())
    return {
        "spend": float(spend + manual_spend) if has_costs else float(legacy_spend),
        "clicks": float(clicks) if has_direct_costs else float(legacy.get("clicks", 0)),
        "visits": float(visits) if has_visits else float(legacy.get("visits", 0)),
    }


async def expenses_by_article(
    session: AsyncSession, period: str, legal_entity: str = "all"
) -> list[dict]:
    """Автоматические расходы Директа и ручные расходы по статьям."""
    now = datetime.now(UTC)
    start = _period_start(period, now)
    end = _period_end(period, now)
    direct_where = [AdCost.date.is_not(None), AdCost.date >= start]
    manual_where = [ManualExpense.spent_at >= start]
    if end is not None:
        direct_where.append(AdCost.date < end)
        manual_where.append(ManualExpense.spent_at < end)
    if legal_entity and legal_entity != "all":
        direct_where.append(AdCost.legal_entity_key == legal_entity)
        manual_where.append(ManualExpense.legal_entity_key == legal_entity)

    direct = (await session.execute(
        select(func.coalesce(func.sum(AdCost.spend), 0)).where(*direct_where)
    )).scalar() or 0
    manual = (await session.execute(
        select(ManualExpense.article, func.sum(ManualExpense.amount))
        .where(*manual_where)
        .group_by(ManualExpense.article)
    )).all()
    rows = [
        {"article": article, "amount": float(amount or 0), "source": "manual"}
        for article, amount in manual
        if amount
    ]
    if direct:
        rows.append({
            "article": "Яндекс Директ (автоматически)",
            "amount": float(direct),
            "source": "automatic",
        })
    rows.sort(key=lambda item: (-item["amount"], item["article"]))
    return rows


def _num(value: object) -> float:
    """Терпимый парс числа (себестоимость из пользовательского поля может быть строкой)."""
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(" ", "").replace("\xa0", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


async def period_deals(
    session: AsyncSession,
    period: str,
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
) -> list[Deal]:
    """Сделки дашборда за период с учётом фильтров «менеджер» и «источник»."""
    now = datetime.now(UTC)
    start = _period_start(period, now)
    end = _period_end(period, now)
    stmt = select(Deal).where(
        Deal.on_dashboard.is_(True),
        Deal.created_at.is_not(None),
        Deal.created_at >= start,
    )
    if end is not None:
        stmt = stmt.where(Deal.created_at < end)
    return list((await session.execute(
        _by_deal_filters(stmt, mgr, source, legal_entity, funnel)
    )).scalars().all())


async def _period_baseline(
    session: AsyncSession,
    period: str,
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
) -> dict[str, float]:
    """Реальные KPI за период — по сделкам с created_at в интервале (боевой режим).

    Выигранные сделки определяются по status_class == 'st-ok' (семантика успеха).
    Маржа считается только если сопоставлено поле себестоимости (иначе 0).
    Фильтры «менеджер»/«источник» сужают выборку сделок; рекламные показатели
    (расход/клики/визиты) от них не зависят — см. _ad_totals."""
    rows = await period_deals(session, period, mgr, source, legal_entity, funnel)
    receipt_stmt = select(OneCReceipt).where(
        OneCReceipt.excluded.is_(False),
        OneCReceipt.registrar_date.is_not(None),
        OneCReceipt.registrar_date >= _period_start(period, datetime.now(UTC)),
    )
    end = _period_end(period, datetime.now(UTC))
    if end is not None:
        receipt_stmt = receipt_stmt.where(OneCReceipt.registrar_date < end)
    if legal_entity and legal_entity != "all":
        receipt_stmt = receipt_stmt.where(OneCReceipt.legal_entity_key == legal_entity)
    if ((mgr and mgr != "all") or (source and source != "all")
            or (funnel and funnel != "all")):
        receipt_stmt = receipt_stmt.join(Deal, OneCReceipt.matched_deal_id == Deal.id)
        receipt_stmt = _by_deal_filters(
            receipt_stmt, mgr, source, legal_entity, funnel
        )
    receipts = (await session.execute(receipt_stmt)).scalars().all()
    if settings.onec_endpoint:
        revenue = sum((receipt.amount for receipt in receipts), start=0)
        payments = len(receipts)
    else:
        # Обратная совместимость демо/старых установок до настройки 1С.
        won = [deal for deal in rows if deal.status_class == "st-ok"]
        revenue = sum(int(deal.amount or 0) for deal in won)
        payments = len(won)

    # Расход/клики/визиты — из посуточного сырья источников за тот же период.
    ad = await _ad_totals(session, period, legal_entity)

    return {
        "leads": float(len(rows)),
        "qual": float(sum(1 for d in rows if d.stage not in (None, "Новое обращение"))),
        "deals": float(sum(1 for d in rows if (d.amount or 0) > 0)),
        "invoices": float(sum(1 for d in rows if d.invoice)),
        "payments": float(payments),
        "revenue": float(revenue),
        "margin": float(revenue),
        "spend": ad["spend"],
        "clicks": ad["clicks"],
        "visits": ad["visits"],
        "first_contact": 0.0,
        "overdue": 0.0,
    }


async def _base_and_mult(
    session: AsyncSession,
    period: str,
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
) -> tuple[dict[str, float], float]:
    """Базлайн и множитель: боевой режим — реальная фильтрация по датам (mult=1),
    демо — сохранённый сид × коэффициент периода (как в прототипе)."""
    if settings.data_source == "real":
        return await _period_baseline(
            session, period, mgr, source, legal_entity, funnel
        ), 1.0
    return await _baselines(session), per.mult(period)


async def _baselines(session: AsyncSession) -> dict[str, float]:
    rows = (await session.execute(select(Baseline))).scalars().all()
    return {b.key: b.value for b in rows}


def _minutes(value: float) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{text} мин"


async def _business_kpi_cards(
    session: AsyncSession,
    period: str,
    mgr: str,
    source: str,
    legal_entity: str,
    funnel: str,
) -> list[dict]:
    """Ожидания оплат, две средние суммы и фактический цикл сделки."""
    rows = await period_deals(session, period, mgr, source, legal_entity, funnel)
    from app.services import business_settings

    config = await business_settings.get_settings(session)
    expected_by_funnel = {
        (str(item.get("crm_source")), str(item.get("external_id"))): {
            str(stage).strip().casefold()
            for stage in item.get("expected_payment_stages", ["Заключение Контракта"])
            if str(stage).strip()
        }
        for item in config.get("funnels", [])
    }
    expected = []
    for deal in rows:
        stages = expected_by_funnel.get(
            (deal.crm_source, deal.funnel_id), {"заключение контракта"}
        )
        if str(deal.stage or "").strip().casefold() in stages:
            expected.append(deal)

    won = [deal for deal in rows if deal.status_class == "st-ok" and deal.amount]
    average_contract = (
        sum(int(deal.amount or 0) for deal in won) / len(won) if won else 0
    )

    now = datetime.now(UTC)
    receipt_stmt = select(OneCReceipt).where(
        OneCReceipt.excluded.is_(False),
        OneCReceipt.registrar_date.is_not(None),
        OneCReceipt.registrar_date >= _period_start(period, now),
    )
    end = _period_end(period, now)
    if end is not None:
        receipt_stmt = receipt_stmt.where(OneCReceipt.registrar_date < end)
    if legal_entity and legal_entity != "all":
        receipt_stmt = receipt_stmt.where(OneCReceipt.legal_entity_key == legal_entity)
    if ((mgr and mgr != "all") or (source and source != "all")
            or (funnel and funnel != "all")):
        receipt_stmt = receipt_stmt.join(Deal, OneCReceipt.matched_deal_id == Deal.id)
        receipt_stmt = _by_deal_filters(
            receipt_stmt, mgr, source, legal_entity, funnel
        )
    receipts = (await session.execute(receipt_stmt)).scalars().all()
    average_receipt = (
        sum(float(item.amount or 0) for item in receipts) / len(receipts)
        if receipts else 0
    )

    won_by_id = {deal.id: deal for deal in won if deal.created_at}
    history_rows = []
    if won_by_id:
        history_rows = list((await session.execute(
            select(StageHistory).where(StageHistory.deal_id.in_(won_by_id))
        )).scalars().all())
    closed_at: dict[int, datetime] = {}
    for item in history_rows:
        deal = won_by_id.get(item.deal_id)
        if (
            deal is not None
            and item.changed_at is not None
            and item.to_stage == deal.stage
            and (item.deal_id not in closed_at or item.changed_at < closed_at[item.deal_id])
        ):
            closed_at[item.deal_id] = item.changed_at
    cycle_values = [
        max(0.0, (closed_at[deal_id] - deal.created_at).total_seconds() / 86_400)
        for deal_id, deal in won_by_id.items()
        if deal_id in closed_at and deal.created_at is not None
    ]
    average_cycle = sum(cycle_values) / len(cycle_values) if cycle_values else 0

    common = {
        "trend": "flat", "spark": [], "drill": None,
        "period_label": per.label(period),
    }
    return [
        {
            **common, "key": "expected_payments", "label": "Ожидаемые оплаты",
            "icon": "i-amber", "svg": '<path d="M4 12h16M12 4v16"/>',
            "kind": "money", "value": float(sum(int(d.amount or 0) for d in expected)),
            "display": f.money_short(sum(int(d.amount or 0) for d in expected)),
            "delta": f"{len(expected)} сделок",
        },
        {
            **common, "key": "average_contract", "label": "Средняя сумма договора",
            "icon": "i-cyan", "svg": '<path d="M5 4h14v16H5zM8 9h8M8 13h8"/>',
            "kind": "money", "value": average_contract,
            "display": f.money_short(average_contract) if average_contract else "—",
            "delta": f"{len(won)} продаж",
        },
        {
            **common, "key": "average_receipt", "label": "Средняя сумма поступления",
            "icon": "i-green", "svg": '<path d="M4 7h16v12H4zM8 4h8M8 13h8"/>',
            "kind": "money", "value": average_receipt,
            "display": f.money_short(average_receipt) if average_receipt else "—",
            "delta": f"{len(receipts)} поступлений",
        },
        {
            **common, "key": "deal_cycle", "label": "Средний цикл сделки",
            "icon": "i-indigo", "svg": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
            "kind": "days", "value": average_cycle,
            "display": f"{average_cycle:.1f} дн".replace(".", ",") if cycle_values else "—",
            "delta": f"{len(cycle_values)} сделок",
        },
    ]


async def kpis(
    session: AsyncSession,
    period: str,
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
) -> list[dict]:
    base, m = await _base_and_mult(
        session, period, mgr, source, legal_entity, funnel
    )
    cards = (await session.execute(select(KpiCard).order_by(KpiCard.position))).scalars().all()
    # В боевом режиме демо-дельты и спарклайны из сида не показываем — только
    # реальные значения (тренд формируется на этапе накопления истории).
    real = settings.data_source == "real"
    # Каналы нужны для реального ROMI (карта с static_value в прототипе — «+197%»),
    # и считаются за выбранный период — иначе ROMI не отвечает на переключатель.
    channels_rows = (
        await _period_channels(
            session, period, mgr, source, legal_entity, funnel
        ) if real else []
    )

    out: list[dict] = []
    for c in cards:
        value: float | None = None
        if c.static_value is not None:
            if real:
                # Не показываем демо-строку: считаем ROMI из каналов, иначе «—».
                r = romi_svc.romi(
                    sum(int(ch["margin"] or 0) for ch in channels_rows),
                    sum(int(ch["spend"] or 0) for ch in channels_rows),
                ) if c.key == "romi" else None
                display = f"{r:+d}%" if r is not None else "—"
            else:
                display = c.static_value
        else:
            raw = (base.get(c.base_key or "", 0)) * (m if c.scales else 1)
            value = raw
            if c.kind == "money":
                display = f.money_short(raw)
            elif c.kind == "minutes":
                display = _minutes(raw)
            else:
                display = f.fmt(raw)
        out.append({
            "key": c.key, "label": c.label, "icon": c.icon, "svg": c.svg, "kind": c.kind,
            "value": value, "display": display,
            "trend": "flat" if real else c.trend,
            "delta": "" if real else c.delta,
            "spark": [] if real else c.spark,
            "drill": c.drill, "period_label": per.label(period),
        })
    if real:
        out.extend(
            await _business_kpi_cards(
                session, period, mgr, source, legal_entity, funnel
            )
        )
    return out


async def filter_options(session: AsyncSession) -> dict:
    """Реальные значения для фильтров (менеджеры/каналы/источники) из данных БД.

    Список строится по тем же сделкам, которые реально считают карточки и таблицы:
    только сделки дашборда (``on_dashboard``), а в боевом режиме — ещё и с
    распознанной датой создания (``created_at``). Иначе в фильтре появлялись
    менеджеры и источники (например SOURCE_ID «cpc»), у которых нет ни одной
    учитываемой сделки: выбор такого значения обнулял все витрины при любом периоде,
    и это выглядело как «фильтр не работает». Теперь любой источник из списка при
    каком-то периоде показывает данные, а «пустые» значения справочника не
    предлагаются вовсе."""
    # Базовый предикат «сделка учитывается витринами» — совпадает с period_deals.
    countable = [Deal.on_dashboard.is_(True)]
    if settings.data_source == "real":
        countable.append(Deal.created_at.is_not(None))

    mgrs = (await session.execute(
        select(Deal.mgr)
        .where(*countable, Deal.mgr.is_not(None), Deal.mgr != "—")
        .distinct()
    )).scalars().all()
    chans = (await session.execute(
        select(Channel.name).order_by(Channel.position)
    )).scalars().all()
    srcs = (await session.execute(
        select(Deal.src)
        .where(*countable, Deal.src.is_not(None), Deal.src != "—")
        .distinct()
    )).scalars().all()
    funnel_rows = (await session.execute(
        select(Deal.crm_source, Deal.funnel_id, func.max(Deal.funnel_name))
        .where(*countable, Deal.funnel_id != "")
        .group_by(Deal.crm_source, Deal.funnel_id)
    )).all()
    from app.services import business_settings

    configured = await business_settings.get_settings(session)
    configured_funnels = {
        (str(item.get("crm_source")), str(item.get("external_id"))): str(
            item.get("name") or ""
        )
        for item in configured.get("funnels", [])
    }
    source_names = {
        str(item.get("key")): str(item.get("name") or item.get("key") or "")
        for item in configured.get("crm_sources", [])
    }
    entities = [
        {"value": item["key"], "label": item["name"]}
        for item in configured.get("legal_entities", [])
        if item.get("enabled", True)
    ]
    return {
        "managers": sorted({m for m in mgrs if m}),
        "channels": list(chans),
        "sources": sorted({s for s in srcs if s}),
        "legal_entities": entities,
        "funnels": [
            {
                "value": f"{crm_source}:{funnel_id}",
                "label": (
                    configured_funnels.get((crm_source, funnel_id))
                    or funnel_name
                    or f"Воронка {funnel_id}"
                ) + (
                    f" · {source_names[crm_source]}"
                    if crm_source in source_names else ""
                ),
            }
            for crm_source, funnel_id, funnel_name in sorted(
                funnel_rows, key=lambda row: ((row[2] or "").lower(), row[0], row[1])
            )
        ],
    }


async def funnel(
    session: AsyncSession,
    period: str,
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
) -> list[dict]:
    base, m = await _base_and_mult(
        session, period, mgr, source, legal_entity, funnel
    )
    stages = [
        ("leads", "Лиды"), ("qual", "Квалификация"), ("deals", "Сделки"),
        ("invoices", "Счета"), ("payments", "Оплаты"),
    ]
    return [{"label": label, "value": round(base.get(key, 0) * m)} for key, label in stages]


# Палитра для источников лидов (SOURCE_ID Битрикс24 — произвольный справочник).
_SOURCE_COLORS = ["#635BFF", "#9E77ED", "#1BA9C7", "#12B76A", "#F79009", "#F04438", "#8E96AD"]


async def sources(
    session: AsyncSession, period: str = per.DEFAULT_PERIOD,
    mgr: str = "all", source: str = "all", legal_entity: str = "all",
    funnel: str = "all",
) -> list[dict]:
    """Источники лидов за период.

    В боевом режиме считаем по источнику сделки (SOURCE_ID Битрикс24): так
    диаграмма охватывает все сделки, отвечает на переключатель периода и на
    фильтры дашборда. В демо — сохранённые каналы прототипа."""
    if settings.data_source != "real":
        chs = (await session.execute(select(Channel).order_by(Channel.position))).scalars().all()
        return [
            {"name": c.name, "short_name": f.short_channel(c.name),
             "color": c.color, "leads": c.leads}
            for c in chs
        ]

    deals = await period_deals(session, period, mgr, source, legal_entity, funnel)
    counts: dict[str, int] = {}
    for d in deals:
        counts[d.src or "—"] = counts.get(d.src or "—", 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        {"name": name, "short_name": f.short_channel(name),
         "color": _SOURCE_COLORS[i % len(_SOURCE_COLORS)], "leads": n}
        for i, (name, n) in enumerate(ordered)
    ]


async def revenue_series(
    session: AsyncSession,
    period: str,
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
) -> dict:
    base, m = await _base_and_mult(
        session, period, mgr, source, legal_entity, funnel
    )
    days = ["09", "11", "13", "15", "17"] if per.norm_period(period) == "today" \
        else ["1", "5", "10", "15", "20", "25", "30"]
    total_rev = base.get("revenue", 0) * m
    total_margin = base.get("margin", 0) * m
    if settings.data_source == "real":
        # Посуточной истории пока нет — показываем ровное распределение реального
        # итога, без придуманной кривой роста и синтетической маржи (как в демо).
        revenue = [round(total_rev / len(days))] * len(days)
        margin = [round(total_margin / len(days))] * len(days)
    else:
        per_day = total_rev / len(days)
        revenue = [round(per_day * (0.7 + i * 0.09)) for i in range(len(days))]
        margin = [round(v * 0.34) for v in revenue]
    return {"days": days, "revenue": revenue, "margin": margin}


async def _period_channels(
    session: AsyncSession,
    period: str,
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
) -> list[dict]:
    """Каналы за период (посуточное сырьё) либо сохранённые строки как резерв."""
    from app.services import channels as ch_svc

    rebuilt = (
        await ch_svc.for_period(
            session, period, mgr=mgr, source=source, legal_entity=legal_entity,
            funnel=funnel,
        )
        if settings.data_source == "real" else None
    )
    if rebuilt is not None:
        return rebuilt
    rows = (await session.execute(select(Channel).order_by(Channel.position))).scalars().all()
    return [
        {"name": c.name, "color": c.color, "spend": c.spend, "leads": c.leads,
         "deals": c.deals, "payments": c.payments, "revenue": c.revenue, "margin": c.margin}
        for c in rows
    ]


async def romi_by_channel(
    session: AsyncSession, period: str = per.DEFAULT_PERIOD,
    mgr: str = "all", source: str = "all", legal_entity: str = "all",
    funnel: str = "all",
) -> list[dict]:
    chs = await _period_channels(session, period, mgr, source, legal_entity, funnel)
    out = []
    for c in chs:
        r = f.romi_of(c["spend"], c["margin"])
        if r is not None:
            out.append({"name": c["name"], "short_name": f.short_channel(c["name"]), "romi": r})
    return out


async def attention(
    session: AsyncSession,
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
) -> dict:
    """Блок «Что требует внимания сейчас».

    Период не применяется намеренно (блок показывает состояние на текущий момент),
    но фильтры «менеджер»/«источник» сужают выборку — иначе они не действовали бы
    на самую заметную часть дашборда."""
    from app.services import violations as vio
    from app.services.integrations_config import get_recompute_status

    res = await vio.evaluate_current(
        session, mgr=mgr, source=source, legal_entity=legal_entity, funnel=funnel
    )
    regular = res["regular"]
    review = res["review"]
    cap = await vio.risk_amount_cap(session)
    money_at_risk = vio.money_at_risk(regular, cap)
    risk_stmt = select(Deal).where(Deal.risk.is_not(None), Deal.on_dashboard.is_(True))
    risk_leads = (await session.execute(
        _by_deal_filters(risk_stmt, mgr, source, legal_entity, funnel)
    )).scalars().all()

    # Реальные счётчики и суммы по типам нарушений (сумма — с дедупом и фильтром выбросов).
    def _count(ptype: str) -> int:
        return sum(1 for v in regular if v.get("ptype") == ptype)

    def _money(ptype: str) -> int:
        by_deal: dict[str, int] = {}
        for v in regular:
            if v.get("ptype") == ptype and v.get("severity") == "over":
                amount = int(v.get("amount") or 0)
                if cap and amount > cap:
                    continue
                by_deal[str(v.get("ref") or v.get("name"))] = amount
        return sum(by_deal.values())

    # Число источников с ошибкой/пропуском в последнем пересчёте.
    rc = await get_recompute_status(session)
    src_errors = sum(1 for s in (rc.get("sources") or {}).values()
                     if s.get("status") in ("error", "skipped"))

    tiles = [
        {"n": _count("overdue_contact"), "label": "Просроченные лиды",
         "sub": "первый контакт > норматива",
         "cls": "red", "icon": "clock", "drill": "monitor:overdue_contact"},
        {"n": _count("no_task"), "label": "Сделки без задач",
         "sub": f"{f.money(_money('no_task'))} под риском",
         "cls": "amber", "icon": "task", "drill": "monitor:no_task"},
        {"n": _count("stuck"), "label": "Сделки без движения",
         "sub": f"{f.money(_money('stuck'))} под риском",
         "cls": "red", "icon": "freeze", "drill": "monitor:stuck"},
        {"n": _count("no_recontact"), "label": "Без повторного касания",
         "sub": f"{f.money(_money('no_recontact'))} под риском",
         "cls": "amber", "icon": "touch", "drill": "monitor:no_recontact"},
        {"n": len(review), "label": "Отказы / спам на проверке",
         "sub": "оценочные нарушения",
         "cls": "violet", "icon": "flag", "drill": "monitor:spam"},
        {"n": _count("fields"), "label": "Не заполнены поля",
         "sub": "обязательные поля сделки",
         "cls": "amber", "icon": "romi", "drill": "monitor:fields"},
        {"n": src_errors, "label": "Ошибки источников данных",
         "sub": "проверьте интеграции",
         "cls": "gray", "icon": "plug", "drill": "data"},
    ]
    return {
        "money_at_risk": money_at_risk,
        "money_at_risk_display": f.money(money_at_risk),
        "risk_leads": len(risk_leads),
        "tiles": tiles,
    }


def _manager_zone(overdue: int, notask: int) -> tuple[str, str]:
    """Зона менеджера по числу просрочек/сделок без задачи."""
    if overdue >= 2 or notask >= 2:
        return "зона риска", "t-red"
    if overdue >= 1 or notask >= 1:
        return "наблюдение", "t-amber"
    return "в норме", "t-green"


async def _managers_from_deals(
    session: AsyncSession,
    period: str,
    mgr: str = "all",
    source: str = "all",
    legal_entity: str = "all",
    funnel: str = "all",
) -> list[dict]:
    """Агрегаты по менеджерам из реальных сделок Битрикс24 (боевой режим).

    Имя менеджера уже сопоставлено при выгрузке (ASSIGNED_BY_ID → ФИО через
    справочник сотрудников). Выборка ограничена периодом и фильтрами дашборда.
    Просрочки и «сделки без задачи» берём из движка регламента (те же нарушения,
    что на «Мониторинге»)."""
    now = datetime.now(UTC)
    start = _period_start(period, now)
    end = _period_end(period, now)
    stmt = select(Deal).where(
        Deal.on_dashboard.is_(True), Deal.mgr.is_not(None), Deal.mgr != "—",
        Deal.created_at.is_not(None), Deal.created_at >= start,
    )
    if end is not None:
        stmt = stmt.where(Deal.created_at < end)
    deals = (
        await session.execute(_by_deal_filters(stmt, mgr, source, legal_entity, funnel))
    ).scalars().all()
    if not deals:
        return []

    # Нарушения по менеджерам: просрочки (over) и «нет задачи» (ptype no_task).
    from app.services import violations as vio
    evaluated = await vio.evaluate_current(
        session, mgr=mgr, source=source, legal_entity=legal_entity, funnel=funnel
    )
    overdue: dict[str, int] = {}
    notask: dict[str, int] = {}
    for v in evaluated.get("regular", []):
        name = v.get("mgr")
        if not name:
            continue
        if v.get("over"):
            overdue[name] = overdue.get(name, 0) + 1
        if v.get("ptype") == "no_task":
            notask[name] = notask.get(name, 0) + 1

    agg: dict[str, dict] = {}
    for d in deals:
        m = agg.setdefault(d.mgr, {
            "name": d.mgr, "inwork": 0, "invoices": 0, "payments": 0, "paysum": 0,
        })
        if d.status_class == "st-mid":  # в работе (не выиграна и не проиграна)
            m["inwork"] += 1
        if d.invoice:
            m["invoices"] += 1

    if settings.onec_endpoint:
        receipt_stmt = (
            select(Deal.mgr, func.count(OneCReceipt.id), func.sum(OneCReceipt.amount))
            .join(Deal, OneCReceipt.matched_deal_id == Deal.id)
            .where(
                OneCReceipt.excluded.is_(False),
                OneCReceipt.registrar_date.is_not(None),
                OneCReceipt.registrar_date >= start,
            )
            .group_by(Deal.mgr)
        )
        if end is not None:
            receipt_stmt = receipt_stmt.where(OneCReceipt.registrar_date < end)
        receipt_stmt = _by_deal_filters(
            receipt_stmt, mgr=mgr, source=source, legal_entity=legal_entity,
            funnel=funnel,
        )
        for manager_name, count, amount in (await session.execute(receipt_stmt)).all():
            item = agg.setdefault(
                manager_name,
                {
                    "name": manager_name,
                    "inwork": 0,
                    "invoices": 0,
                    "payments": 0,
                    "paysum": 0,
                },
            )
            item["payments"] = int(count or 0)
            item["paysum"] = round(amount or 0)
    else:
        for deal in deals:
            if deal.status_class == "st-ok":
                item = agg[deal.mgr]
                item["payments"] += 1
                item["paysum"] += int(deal.amount or 0)

    out: list[dict] = []
    for m in agg.values():
        ov, nt = overdue.get(m["name"], 0), notask.get(m["name"], 0)
        zone_label, zone_class = _manager_zone(ov, nt)
        out.append({
            **m, "overdue": ov, "notask": nt, "fc": "—",
            "paysum_display": f.money(m["paysum"]),
            "zone_label": zone_label, "zone_class": zone_class,
        })
    # Самые результативные — выше; при равенстве по имени.
    out.sort(key=lambda x: (-x["paysum"], x["name"]))
    return out


async def managers(
    session: AsyncSession, period: str = per.DEFAULT_PERIOD,
    mgr: str = "all", source: str = "all", legal_entity: str = "all",
    funnel: str = "all",
) -> list[dict]:
    if settings.data_source == "real":
        return await _managers_from_deals(
            session, period, mgr, source, legal_entity, funnel
        )
    rows = (await session.execute(
        select(ManagerControl).order_by(ManagerControl.position)
    )).scalars().all()
    return [
        {
            "name": m.name, "inwork": m.inwork, "overdue": m.overdue, "notask": m.notask,
            "fc": m.fc, "invoices": m.invoices, "payments": m.payments,
            "paysum": m.paysum, "paysum_display": f.money(m.paysum),
            "zone_label": m.zone_label, "zone_class": m.zone_class,
        }
        for m in rows
    ]


async def leads(
    session: AsyncSession, mgr: str = "all", source: str = "all",
    risk: str | None = None, period: str = "30", legal_entity: str = "all",
    funnel: str = "all",
) -> list[dict]:
    stmt = select(Deal).where(Deal.on_dashboard.is_(True))
    # В боевом режиме список лидов следует выбранному периоду (по дате создания),
    # чтобы переключатель периода менял и таблицу «Обработка лидов».
    if settings.data_source == "real":
        now = datetime.now(UTC)
        start = _period_start(period, now)
        end = _period_end(period, now)
        stmt = stmt.where(Deal.created_at.is_not(None), Deal.created_at >= start)
        if end is not None:
            stmt = stmt.where(Deal.created_at < end)
    stmt = _by_deal_filters(stmt, mgr, source, legal_entity, funnel)
    if risk == "risk":
        stmt = stmt.where(Deal.risk.is_not(None))
    stmt = stmt.order_by(Deal.position)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "name": d.name, "src": d.src, "mgr": d.mgr,
            "legal_entity_key": d.legal_entity_key,
            "status_label": d.status_label, "status_class": d.status_class,
            "fc": d.first_contact, "call": d.call, "inv": d.invoice, "pay": d.paid,
            "amount": d.amount, "amount_display": f.money(d.amount) if d.amount else "—",
            "risk": d.risk, "tags": d.tags, "ai": d.ai_comment, "reason": d.refuse_reason,
        }
        for d in rows
    ]
