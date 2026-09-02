"""Конвейер выгрузки источников и пересчёта сквозной аналитики (боевой режим).

Схема: адаптеры (сырьё) → БД → детерминированный пересчёт → витрины.
Атрибуция сделки к каналу/кампании — по UTM/кампании/источнику; расход Директа
приводится к базе без НДС (методика, раздел 4 ТЗ); маржа — из прибыльности
МойСклад. Запускается джобами планировщика и командой `python -m app.services.ingest`.

Чистые функции агрегации покрыты тестами; сетевые вызовы идут через боевые
адаптеры и в mock-режиме не выполняются.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.integrations import factory
from app.models import (
    AdCost,
    Baseline,
    BudgetRec,
    Campaign,
    Channel,
    Deal,
    MinusWord,
    Product,
    Visit,
)
from app.services import format as f
from app.services import period as per
from app.services import rec_style, romi
from app.services import sources as src_svc

logger = get_logger("lawyer.ingest")

# Тип колбэка прогресса: получает короткий текст шага.
Progress = Callable[[str], Awaitable[None]]

# Глубина выгрузки сделок Битрикс24 — общее окно источников (per.WINDOW_DAYS):
# покрывает максимальный период дашборда (квартал ≈ 90 дней), чтобы фильтрация по
# датам работала для всех периодов, а не только для 30 дней.
_DEALS_WINDOW_DAYS = per.WINDOW_DAYS


def _parse_dt(value: str | None) -> datetime | None:
    """Безопасный разбор ISO-даты Битрикс24 (с таймзоной) в datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _parse_date(value: str | None) -> datetime | None:
    """Дата отчёта источника (YYYY-MM-DD) → datetime в UTC."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _stage_class(stage: str | None, semantic: str | None) -> str:
    """CSS-класс статуса лида: по семантике Битрикс (S/F/P), иначе по названию."""
    if semantic == "S":
        return "st-ok"
    if semantic == "F":
        return "st-bad"
    s = (stage or "").lower()
    if any(k in s for k in ("оплач", "успешно", "реализ", "won")):
        return "st-ok"
    if any(k in s for k in ("отказ", "спам", "lose", "fail")):
        return "st-bad"
    return "st-mid"


def _deal_from_bitrix(
    position: int, nd: dict,
    users: dict[str, str] | None = None,
    stages: dict[str, str] | None = None,
    phones: dict[str, str] | None = None,
    sources: dict[str, str] | None = None,
    has_open_action: bool = False,
) -> Deal:
    """Нормализованная сделка Битрикс24 → строка Deal (минимальный безопасный маппинг).

    users: ID сотрудника → ФИО; stages: STAGE_ID → название; phones: contact_id →
    телефон; sources: SOURCE_ID → название источника.
    """
    code = nd.get("stage")
    semantic = nd.get("semantic")
    stage = (stages or {}).get(str(code)) or code  # человекочитаемое название стадии
    # У сделки без ответственного ASSIGNED_BY_ID приходит нулём — это «не назначен»,
    # а не идентификатор: иначе задача в Битриксе уходила в «Не распределено».
    mgr_id = str(nd.get("mgr") or "").strip()
    if mgr_id == "0":
        mgr_id = ""
    mgr = (users or {}).get(mgr_id) or mgr_id or "—"
    contact_id = str(nd.get("contact_id") or "").strip()
    phone = (phones or {}).get(contact_id)
    src_code = str(nd.get("src") or "").strip()
    # Название источника вместо служебного кода портала («site» → «Сайт»);
    # обрезаем под ширину колонки — справочник источников на портале произвольный.
    resolved = ((sources or {}).get(src_code) or src_code or "—")[:64]
    # Сырые коды («call», «mail», «cpc»), которые портал не разрешил в название,
    # сворачиваем в понятные названия и объединяем с основными источниками.
    src = src_svc.canonical_source(resolved)
    custom = nd.get("custom") or {}
    return Deal(
        position=position,
        on_dashboard=True,
        ref=nd.get("ref", ""),
        external_id=nd.get("external_id"),
        name=nd.get("name") or "Без названия",
        src=src,
        campaign=nd.get("campaign"),
        utm=nd.get("utm"),
        mgr=mgr,
        mgr_id=mgr_id or None,
        phone=phone,
        client_type=custom.get("client_type") or None,
        refuse_reason=custom.get("refuse_reason") or "",
        custom=custom or None,
        status_label=str(stage or "—"),
        status_class=_stage_class(stage, semantic),
        stage=stage,
        amount=int(nd.get("amount") or 0),
        first_contact="—",
        created_at=_parse_dt(nd.get("created")),
        last_activity_at=_parse_dt(nd.get("last_activity")),
        has_open_action=has_open_action,
    )

# Правила отнесения кампании к каналу (по префиксу названия кампании).
# Классификация кампании в канал по ключевым словам в названии (регистронезависимо).
CHANNEL_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("поиск", "search", "srch"), "Яндекс Директ — Поиск", "#635BFF"),
    (("рся", "сети", "network", "rsya", "смарт"), "Яндекс Директ — РСЯ", "#9E77ED"),
]
DEFAULT_CHANNEL = ("Яндекс Директ — прочее", "#1BA9C7")


def channel_for_campaign(campaign_name: str) -> tuple[str, str]:
    """Канал (имя, цвет) по названию кампании (по ключевым словам, регистронезависимо)."""
    low = (campaign_name or "").lower()
    for keywords, channel, color in CHANNEL_RULES:
        if any(k in low for k in keywords):
            return channel, color
    return DEFAULT_CHANNEL


def _deal_cost(deal: dict) -> int:
    """Себестоимость сделки из сопоставленного поля (custom['cost']), ₽."""
    raw = (deal.get("custom") or {}).get("cost")
    if raw is None:
        return 0
    try:
        return int(float(str(raw).replace(" ", "").replace("\xa0", "").replace(",", ".")))
    except (TypeError, ValueError):
        return 0


def _row_spend_net(row: dict) -> int:
    """Расход строки в базе без НДС.

    Директ отдаёт расход с НДС (`spend_gross`) — приводим; сохранённые строки
    AdCost уже нормализованы (`spend`), их берём как есть.
    """
    if row.get("spend") is not None:
        return int(row["spend"] or 0)
    return round(romi.vat_to_net(row.get("spend_gross", 0)))


def aggregate_channels(
    direct_costs: list[dict],
    deals: list[dict] | None = None,
) -> list[dict]:
    """Строит витрину каналов/кампаний из расхода Директа + атрибуции сделок.

    Расход приводится к базе без НДС. Строки статистики приходят с разбивкой по
    дням (кампания × дата), поэтому кампании сворачиваются по ключу (id/название):
    иначе одна кампания попадала бы в таблицу отдельной строкой на каждый день.
    Сделки привязываются к кампаниям по utm_campaign (сопоставление с id или
    названием кампании Директа); по привязанным сделкам считаются
    лиды/сделки/оплаты/выручка/маржа. Маржа = выручка − себестоимость (из
    сопоставленного поля; без него ≈ выручка).
    """
    deals = deals or []
    channels: dict[str, dict] = {}
    camp_index: dict[str, dict] = {}  # ключ (id/имя) → запись кампании

    for row in direct_costs:
        camp = row.get("campaign", "")
        cid = str(row.get("campaign_id") or "").strip()
        spend_net = _row_spend_net(row)
        ch_name, color = channel_for_campaign(camp)
        ch = channels.setdefault(ch_name, {
            "name": ch_name, "color": color, "spend": 0,
            "leads": 0, "deals": 0, "payments": 0, "revenue": 0, "margin": 0,
            "campaigns": [],
        })
        # Ключ сворачивания дневных строк одной кампании (id надёжнее названия).
        key = cid or camp.strip().lower()
        crec = camp_index.get(key)
        if crec is None:
            crec = {
                "name": camp, "spend": 0,
                "leads": 0, "deals": 0, "payments": 0, "revenue": 0, "margin": 0,
            }
            ch["campaigns"].append(crec)
            if cid:
                camp_index[cid] = crec
            if camp:
                camp_index[camp.strip().lower()] = crec
        crec["spend"] += spend_net

    # Атрибуция сделок к кампаниям по utm_campaign (id или название).
    for d in deals:
        key = str(d.get("campaign") or "").strip()
        if not key:
            continue
        crec = camp_index.get(key) or camp_index.get(key.lower())
        if crec is None:
            continue
        amount = int(d.get("amount") or 0)
        crec["leads"] += 1
        if amount > 0:
            crec["deals"] += 1
        if d.get("semantic") == "S":  # выигранная сделка
            crec["payments"] += 1
            crec["revenue"] += amount
            crec["margin"] += amount - _deal_cost(d)

    # Свернуть кампании в каналы.
    for ch in channels.values():
        for k in ("spend", "leads", "deals", "payments", "revenue", "margin"):
            ch[k] = sum(c[k] for c in ch["campaigns"])
    return list(channels.values())


_MINUS_WORD_LIMIT = 200


def budget_recs_from_channels(channels: list[dict]) -> list[dict]:
    """Рекомендации по бюджету из каналов — по ROMI (детерминированная логика).

    Масштабировать / Под наблюдением / Проверить / Ограничить — по порогам ROMI.
    Проблемные каналы (Ограничить/Проверить) идут первыми."""
    recs: list[dict] = []
    for ch in channels:
        spend = int(ch.get("spend") or 0)
        if spend <= 0:
            continue
        margin = int(ch.get("margin") or 0)
        revenue = int(ch.get("revenue") or 0)
        payments = int(ch.get("payments") or 0)
        r = romi.romi(margin, spend)
        if r is None:
            continue
        if r >= 200:
            key = "scale"
        elif r >= 120:
            key = "watch"
        elif r >= 80:
            key = "check"
        else:
            key = "limit"
        label = rec_style.KEY_LABELS[key]
        tag_class, ic, svg = rec_style.REC_STYLE[key]
        text = {
            "scale": f"Высокий ROMI ({r}%): канал окупается — есть смысл наращивать бюджет.",
            "watch": f"ROMI ({r}%) в пределах цели — держим бюджет и наблюдаем за динамикой.",
            "check": f"ROMI ({r}%) ниже цели — проверить ставки, связки и качество трафика.",
            "limit": f"ROMI ({r}%) ниже окупаемости — сократить расход или пересобрать кампании.",
        }[key]
        recs.append({
            "title": ch.get("name", ""), "tag_label": label, "tag_class": tag_class,
            "ic": ic, "svg": svg, "text": text,
            "why": f"Расход {f.money(spend)}, выручка {f.money(revenue)}, "
                   f"оплат {payments}, ROMI {r}%.",
            "impact": (f"− до {f.money(spend)}/мес" if key == "limit"
                       else "потенциал роста выручки" if key == "scale" else ""),
            "src": ["Яндекс Директ", "МойСклад"], "conf": "высокая",
            # Маржа == выручка → себестоимость не сопоставлена (маржа неточная).
            "dep": margin == revenue,
        })
    recs.sort(key=lambda x: rec_style.TAG_ORDER.get(x["tag_class"], 9))
    return recs


def minus_word_candidates(search_queries: list[dict]) -> list[dict]:
    """Кандидаты в минус-слова: поисковые запросы с расходом и без конверсий.

    Это фразы, на которые тратится бюджет без результата — топ по расходу (без НДС)."""
    out: list[dict] = []
    for q in search_queries:
        spend_net = round(romi.vat_to_net(q.get("spend", 0)))
        if spend_net <= 0 or int(q.get("conv") or 0) > 0:
            continue
        out.append({
            "phrase": q.get("phrase", ""), "camp": q.get("camp", ""),
            "shows": int(q.get("shows") or 0), "clicks": int(q.get("clicks") or 0),
            "spend": spend_net, "reason": "Расход без конверсий",
        })
    out.sort(key=lambda x: x["spend"], reverse=True)
    return out[:_MINUS_WORD_LIMIT]


def baseline_from(channels: list[dict], deals: list[dict]) -> dict[str, float]:
    """Базовые KPI из витрины каналов и сделок.

    Выручка и «оплаты» берутся из выигранных сделок Битрикс (семантика стадии S —
    успех), а не из рекламной атрибуции: так «Выручка» на дашборде отражает реальные
    закрытые сделки, даже когда рекламные каналы не подключены."""
    won = [d for d in deals if d.get("semantic") == "S"]
    return {
        "leads": float(len(deals)),
        "qual": float(sum(1 for d in deals if d.get("stage") not in (None, "Новое обращение"))),
        "deals": float(sum(1 for d in deals if d.get("amount", 0) > 0)),
        "invoices": float(sum(1 for d in deals if d.get("invoice"))),
        "payments": float(len(won)),  # оплаты ≈ выигранные сделки
        "revenue": float(sum(int(d.get("amount") or 0) for d in won)),
        "margin": float(sum(c["margin"] for c in channels)),  # маржа — из атрибуции каналов
        "spend": float(sum(c["spend"] or 0 for c in channels)),
        "first_contact": 0.0,
        "overdue": 0.0,
    }


# ------------------- Лёгкая синхронизация сделок (боевой режим) -------------------

# Поля сделки, которые приходят из Битрикс24 и обновляются при синхронизации.
# Остальное (локальные задачи, история этапов) принадлежит нам и не затирается.
# position сюда не входит: порядок задаётся отдельно (см. refresh_deals).
_DEAL_SYNC_FIELDS = (
    "on_dashboard", "ref", "name", "src", "campaign", "utm", "mgr", "mgr_id",
    "phone", "client_type", "refuse_reason", "custom", "status_label", "status_class",
    "stage", "amount", "created_at", "last_activity_at", "has_open_action",
)


def _open_action_ids(deals: list[dict]) -> set[str]:
    """external_id сделок с открытой задачей/делом в Битрикс24 (best-effort).

    Признак нужен правилу «Сделка без задачи»: без него любая выгруженная сделка
    выглядит как «без задачи». Сбой (нет прав, недоступен портал) не должен ронять
    синхронизацию — тогда признак остаётся пустым, поведение как раньше.
    """
    ids = [str(d.get("external_id")) for d in deals if d.get("external_id")]
    if not ids:
        return set()
    try:
        return factory.get_bitrix24().fetch_open_action_deal_ids(ids)
    except Exception as exc:  # noqa: BLE001 — признак задач/дел необязателен
        logger.warning("Битрикс24: задачи/дела сделок недоступны: %s", exc)
        return set()

# Запас перекрытия окна изменений: покрывает пропущенные тики планировщика и
# расхождение часов с порталом, чтобы правка сделки не потерялась между запусками.
_SYNC_OVERLAP_MINUTES = 30


def _apply_deal_fields(target: Deal, fresh: Deal) -> None:
    """Переносит поля из свежей выгрузки в существующую строку сделки."""
    for name in _DEAL_SYNC_FIELDS:
        setattr(target, name, getattr(fresh, name))


async def _bitrix_dictionaries(
    deals: list[dict], progress: Progress | None = None
) -> tuple[dict, dict, dict, dict]:
    """Справочники сотрудников/стадий/источников и телефоны контактов (best-effort)."""
    b24 = factory.get_bitrix24()
    if progress:
        await progress("Битрикс24: справочники сотрудников, стадий и источников…")
    users: dict[str, str] = {}
    stages: dict[str, str] = {}
    sources: dict[str, str] = {}
    phones: dict[str, str] = {}
    try:
        users = {u["id"]: u["name"] for u in b24.fetch_users()}
    except Exception as exc:  # noqa: BLE001 — имена необязательны
        logger.warning("Битрикс24: справочник сотрудников недоступен: %s", exc)
    try:
        stages = {x["id"]: x["name"] for x in b24.fetch_stages()}
    except Exception as exc:  # noqa: BLE001 — названия стадий необязательны
        logger.warning("Битрикс24: справочник стадий недоступен: %s", exc)
    try:
        sources = {x["id"]: x["name"] for x in b24.fetch_sources()}
    except Exception as exc:  # noqa: BLE001 — названия источников необязательны
        logger.warning("Битрикс24: справочник источников недоступен: %s", exc)
    try:
        contact_ids = [str(d.get("contact_id")) for d in deals if d.get("contact_id")]
        if contact_ids:
            if progress:
                await progress("Битрикс24: телефоны контактов…")
            phones = b24.fetch_contact_phones(contact_ids)
    except Exception as exc:  # noqa: BLE001 — телефоны необязательны
        logger.warning("Битрикс24: телефоны контактов недоступны: %s", exc)
    return users, stages, sources, phones


async def refresh_deals(session: AsyncSession, *, full: bool = False) -> dict:
    """Синхронизирует сделки из Битрикс24 без выгрузки рекламных источников.

    Это быстрый путь для событий портала и частой сверки: рекламные витрины
    (Директ/Метрика/МойСклад) не трогаются, тянутся только сделки. По умолчанию
    берутся сделки, изменённые за последнее окно; full=True перечитывает всё окно
    дашборда и убирает сделки, исчезнувшие из портала.

    Строки сделок обновляются на месте (по ID Битрикс24), а не пересоздаются:
    иначе при каждой сверке терялись бы локально поставленные задачи и «сделки
    без задач» возвращались бы в мониторинг сразу после постановки задачи.
    """
    if settings.data_source != "real":
        return {"skipped": True, "reason": "демо-режим", "updated": 0, "created": 0}
    if not settings.bitrix24_webhook_url:
        return {"skipped": True, "reason": "Битрикс24 не настроен", "updated": 0, "created": 0}

    from app.services.integrations_config import get_field_map
    extra_fields = (await get_field_map(session)).get("fields") or {}

    now = datetime.now(UTC)
    if full:
        window = (now - timedelta(days=_DEALS_WINDOW_DAYS)).strftime("%Y-%m-%dT00:00:00+03:00")
        raw = factory.get_bitrix24().fetch_deals(
            created_after=window, extra_fields=extra_fields)
    else:
        since = (now - timedelta(minutes=_SYNC_OVERLAP_MINUTES)).isoformat(timespec="seconds")
        raw = factory.get_bitrix24().fetch_deals(
            modified_after=since, extra_fields=extra_fields)

    users, stages, sources_map, phones = await _bitrix_dictionaries(raw)
    action_ids = _open_action_ids(raw)

    existing = {
        d.external_id: d
        for d in (await session.execute(select(Deal))).scalars().all()
        if d.external_id
    }
    created = updated = 0
    seen: set[str] = set()
    # Порядок сделок. При полном чтении окна он задаётся выдачей портала (по дате
    # создания). При частичной сверке позиции существующих строк не трогаем, а
    # новые дописываем в конец: иначе номера столкнулись бы с уже сохранёнными,
    # и порядок таблицы лидов (а с ним и выбор «оригинала» среди дублей) поплыл бы.
    next_position = max((d.position for d in existing.values()), default=-1) + 1
    for i, nd in enumerate(raw):
        fresh = _deal_from_bitrix(
            i, nd, users, stages, phones, sources_map,
            has_open_action=str(nd.get("external_id")) in action_ids,
        )
        ext = fresh.external_id
        current = existing.get(ext) if ext else None
        if current is None:
            if not full:
                fresh.position = next_position
                next_position += 1
            session.add(fresh)
            created += 1
        else:
            _apply_deal_fields(current, fresh)
            if full:
                current.position = i
            updated += 1
        if ext:
            seen.add(ext)

    removed = 0
    if full:
        # Только при полном чтении окна известно, каких сделок в портале больше нет.
        for ext, row in existing.items():
            if ext not in seen:
                await session.delete(row)
                removed += 1

    await session.commit()
    # Доводим уже сохранённые строки к каноничным источникам: частичная сверка
    # трогает только изменённые сделки, поэтому старые коды («call», «cpc») чиним
    # отдельным идемпотентным проходом по всей таблице.
    normalized = await src_svc.normalize_existing(session)
    logger.info(
        "Сверка сделок Битрикс24: создано=%d обновлено=%d удалено=%d источники=%d (full=%s)",
        created, updated, removed, normalized, full,
    )
    return {
        "skipped": False, "created": created, "updated": updated,
        "removed": removed, "full": full,
    }


# --------------------------- Оркестрация (боевой режим) ---------------------------

async def _fetch_source(
    sources: dict, key: str, label: str, fn: Callable[[], list[dict]],
    progress: Progress | None, step_text: str,
) -> list[dict]:
    """Выгружает один источник устойчиво: ошибка/отсутствие креда не валит пересчёт."""
    if progress:
        await progress(step_text)
    try:
        rows = fn()
        sources[key] = {"status": "ok", "count": len(rows)}
        return rows
    except Exception as exc:  # noqa: BLE001 — источник недоступен → отмечаем и продолжаем
        logger.warning("Источник %s недоступен: %s", key, exc)
        sources[key] = {"status": "error", "message": str(exc)}
        return []


async def ingest_all(session: AsyncSession, progress: Progress | None = None) -> dict:
    """Устойчивый цикл: выгрузка настроенных источников → БД → пересчёт витрин.

    Ненастроенные источники пропускаются (status=skipped), сбойные — помечаются
    ошибкой, но не прерывают пересчёт. Возвращает режим, per-source статус и stats.
    """
    if settings.data_source != "real":
        logger.info("ingest: DATA_SOURCE != real — пропуск (в mock используется сид)")
        return {"mode": settings.data_source, "skipped": True, "sources": {}, "stats": {}}

    sources: dict[str, dict] = {}

    # Сопоставление пользовательских полей Битрикс (со страницы «Интеграции»).
    from app.services.integrations_config import get_field_map
    field_map = await get_field_map(session)
    extra_fields = field_map.get("fields") or {}

    # 1. Сделки Битрикс24 (за окно дашборда — иначе выгружается вся история портала).
    users: dict[str, str] = {}
    stages: dict[str, str] = {}
    phones: dict[str, str] = {}
    sources_map: dict[str, str] = {}
    if settings.bitrix24_webhook_url:
        since = (datetime.now(UTC) - timedelta(days=_DEALS_WINDOW_DAYS)).strftime(
            "%Y-%m-%dT00:00:00+03:00"
        )
        deals = await _fetch_source(
            sources, "bitrix24", "Битрикс24",
            lambda: factory.get_bitrix24().fetch_deals(
                created_after=since, extra_fields=extra_fields),
            progress, f"Битрикс24: загрузка сделок за {_DEALS_WINDOW_DAYS} дней…",
        )
        # Справочники и телефоны контактов — не критично для пересчёта.
        if sources["bitrix24"]["status"] == "ok":
            users, stages, sources_map, phones = await _bitrix_dictionaries(deals, progress)
    else:
        deals = []
        sources["bitrix24"] = {"status": "skipped"}

    # 2. Расход Яндекс Директа (для витрины каналов) + поисковые запросы (минус-слова).
    search_queries: list[dict] = []
    if settings.yandex_oauth_token:
        direct_costs = await _fetch_source(
            sources, "yandex_direct", "Яндекс Директ",
            lambda: factory.get_yandex_direct().fetch_channels(),
            progress, "Яндекс Директ: статистика кампаний…",
        )
        try:
            if progress:
                await progress("Яндекс Директ: поисковые запросы (минус-слова)…")
            search_queries = factory.get_yandex_direct().fetch_search_queries()
        except Exception as exc:  # noqa: BLE001 — минус-слова необязательны
            logger.warning("Яндекс Директ: отчёт по запросам недоступен: %s", exc)
    else:
        direct_costs = []
        sources["yandex_direct"] = {"status": "skipped"}

    # 2b. Визиты Яндекс Метрики (для шага «Визиты» сквозной цепочки).
    metrika_visits: list[dict] = []
    if settings.yandex_oauth_token and settings.yandex_metrika_counter_id:
        metrika_visits = await _fetch_source(
            sources, "yandex_metrika", "Яндекс Метрика",
            lambda: factory.get_yandex_metrika().fetch_visits(),
            progress, "Яндекс Метрика: визиты…",
        )
    else:
        sources["yandex_metrika"] = {"status": "skipped"}

    # 3. Номенклатура МойСклад (себестоимость/бренды).
    # Источник настроен, если задан DSN реплики mpdb ИЛИ токен API (резерв).
    if (settings.moysklad_pg_dsn or "").strip() or settings.moysklad_token:
        products = await _fetch_source(
            sources, "moysklad", "МойСклад",
            lambda: factory.get_moysklad().fetch_products(),
            progress, "МойСклад: номенклатура…",
        )
    else:
        products = []
        sources["moysklad"] = {"status": "skipped"}

    # 4. Пересчёт витрин
    if progress:
        await progress("Пересчёт витрин и показателей…")
    channels = aggregate_channels(direct_costs, deals)
    baseline = baseline_from(channels, deals)
    # Клики (Директ) и визиты (Метрика) — для первых шагов сквозной цепочки.
    baseline["clicks"] = float(sum(int(r.get("clicks") or 0) for r in direct_costs))
    baseline["visits"] = float(sum(int(v.get("visits") or 0) for v in metrika_visits))
    minus_words = minus_word_candidates(search_queries)
    budget_recs = budget_recs_from_channels(channels)

    # 5. Запись (сделки + каналы + продукты + базлайны)
    await session.execute(delete(Deal))  # каскадно чистит задачи/историю этапов
    await session.execute(delete(Campaign))
    await session.execute(delete(Channel))
    await session.execute(delete(AdCost))
    await session.execute(delete(Visit))
    await session.execute(delete(Product))
    await session.execute(delete(Baseline))
    # Демо-таблицы без реального источника (менеджеры/рекомендации/минус-слова/
    # демо-история) в боевом режиме держим пустыми — разделы покажут «нет данных».
    from app.services import data_mode
    await data_mode.clear_no_source_tables(session)

    action_ids = _open_action_ids(deals)
    for i, nd in enumerate(deals):
        session.add(_deal_from_bitrix(
            i, nd, users, stages, phones, sources_map,
            has_open_action=str(nd.get("external_id")) in action_ids,
        ))

    # Сырьё источников по дням — из него считаются расход/клики/визиты за период
    # (иначе показатели остаются одним 30-дневным итогом на все периоды).
    for row in direct_costs:
        session.add(AdCost(
            date=_parse_date(row.get("date")),
            campaign=str(row.get("campaign") or "")[:128],
            campaign_id=str(row.get("campaign_id") or "")[:32] or None,
            spend=_row_spend_net(row),
            clicks=int(row.get("clicks") or 0),
            impressions=int(row.get("impressions") or 0),
        ))
    for row in metrika_visits:
        session.add(Visit(
            date=_parse_date(row.get("date")),
            source=str(row.get("source") or "")[:128],
            visits=int(row.get("visits") or 0),
        ))

    for i, ch in enumerate(channels):
        channel = Channel(
            position=i, name=ch["name"], color=ch["color"], spend=ch["spend"],
            leads=ch["leads"], deals=ch["deals"], payments=ch["payments"],
            revenue=ch["revenue"], margin=ch["margin"],
        )
        for j, camp in enumerate(ch["campaigns"]):
            channel.campaigns.append(Campaign(
                position=j, name=camp["name"], spend=camp["spend"],
                leads=camp["leads"], deals=camp["deals"], payments=camp["payments"],
                revenue=camp["revenue"], margin=camp["margin"],
            ))
        session.add(channel)

    for p in products:
        session.add(Product(
            name=p["name"], brand=p.get("brand"), cost_price=p.get("cost_price", 0),
        ))
    for i, mw in enumerate(minus_words):
        session.add(MinusWord(
            position=i, phrase=mw["phrase"], camp=mw["camp"],
            shows=mw["shows"], clicks=mw["clicks"], spend=mw["spend"],
            conv=0, deals=0, reason=mw["reason"], status="new",
        ))
    for i, rec in enumerate(budget_recs):
        session.add(BudgetRec(
            position=i, ic=rec["ic"], svg=rec["svg"], title=rec["title"],
            tag_label=rec["tag_label"], tag_class=rec["tag_class"], text=rec["text"],
            why=rec["why"], impact=rec["impact"], src=rec["src"],
            conf=rec["conf"], dep=rec["dep"],
        ))
    for key, value in baseline.items():
        session.add(Baseline(key=key, value=value))

    await session.commit()
    stats = {"deals": len(deals), "channels": len(channels), "products": len(products)}
    logger.info("ingest завершён: %s", stats)
    return {"mode": "real", "sources": sources, "stats": stats}


async def main() -> None:
    from app.services.integrations_config import apply_overrides_from_db

    async with SessionLocal() as session:
        # Применяем доступы/режим, сохранённые через UI (иначе процесс видит только env).
        await apply_overrides_from_db(session)
        await ingest_all(session)


if __name__ == "__main__":
    asyncio.run(main())
