"""Конвейер выгрузки источников и пересчёта сквозной аналитики (боевой режим).

Схема: адаптеры (сырьё) → БД → детерминированный пересчёт → витрины.
Атрибуция сделки к каналу/кампании — по UTM/кампании/источнику; расход Директа
приводится к базе без НДС, а оплаты и выручка берутся только из фактических
поступлений 1С:УНФ. Запускается джобами и командой `python -m app.services.ingest`.

Чистые функции агрегации покрыты тестами; сетевые вызовы идут через боевые
адаптеры и в mock-режиме не выполняются.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
    OneCReceipt,
    Product,
    Visit,
)
from app.services import business_settings as business
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

_ONEC_INCOME_TYPES = {
    "ПоступлениеНаСчет",
    "ПоступлениеВКассу",
    "ОперацияПоПлатежнымКартам",
    "ЧекККМ",
}


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
    legal_entity_key: str = "",
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
        crm_source=str(nd.get("crm_source") or "primary")[:32],
        entity_type=str(nd.get("entity_type") or "deal")[:16],
        legal_entity_key=legal_entity_key[:32],
        funnel_id=str(nd.get("funnel_id") or "0")[:48],
        funnel_name=str(nd.get("funnel_name") or "")[:128],
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
    receipts: list[dict] | None = None,
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
    actual_by_deal: dict[str, dict[str, Decimal | int]] = {}
    if receipts is not None:
        for receipt in receipts:
            if receipt.get("excluded"):
                continue
            external_id = str(receipt.get("crm_external_id", "")).strip()
            if not external_id:
                continue
            total = actual_by_deal.setdefault(
                external_id, {"amount": Decimal("0"), "count": 0}
            )
            total["amount"] = Decimal(str(total["amount"])) + Decimal(
                str(receipt.get("amount") or 0)
            )
            total["count"] = int(total["count"]) + 1
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
        if receipts is None:
            # Совместимость старых демо-данных; в бою всегда передаются факты 1С.
            if d.get("semantic") == "S":
                crec["payments"] += 1
                crec["revenue"] += amount
                crec["margin"] += amount - _deal_cost(d)
        else:
            actual = actual_by_deal.get(str(d.get("external_id", "")))
            if actual:
                received = round(Decimal(str(actual["amount"])))
                crec["payments"] += int(actual["count"])
                crec["revenue"] += received
                crec["margin"] += received

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
            "src": ["Яндекс Директ", "1С"], "conf": "высокая",
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


def baseline_from_receipts(
    channels: list[dict], deals: list[dict], receipts: list[dict]
) -> dict[str, float]:
    """KPI, где оплаты и выручка считаются по разрешённым фактам 1С."""
    included = [row for row in receipts if not row.get("excluded")]
    revenue = sum((Decimal(str(row.get("amount") or 0)) for row in included), Decimal("0"))
    result = baseline_from(channels, deals)
    result["payments"] = float(len(included))
    result["revenue"] = float(revenue)
    # Себестоимость юридических услуг в текущем ТЗ не поступает из источника.
    result["margin"] = float(revenue)
    return result


def classify_receipts(rows: list[dict], config: dict) -> list[dict]:
    """Присваивает юрлицо и проверяет статью ДДС/внутренние переводы."""
    entities = config.get("legal_entities", [])
    entity_by_inn = {
        str(item.get("inn", "")).strip(): str(item.get("key", ""))
        for item in entities
        if str(item.get("inn", "")).strip()
    }
    own_inns = set(entity_by_inn)
    out: list[dict] = []
    for source in rows:
        row = dict(source)
        entity_key = entity_by_inn.get(str(row.get("organization_inn", "")).strip(), "")
        row["legal_entity_key"] = entity_key
        counterparty_inn = str(row.get("counterparty_inn", "")).strip()
        operation = business.receipt_article_operation(
            config, entity_key, str(row.get("article_name", ""))
        )
        registrar_type = str(row.get("registrar_type", "")).strip()
        reason = ""
        if registrar_type not in _ONEC_INCOME_TYPES:
            reason = "unsupported_registrar_type" if registrar_type else "missing_registrar_type"
        elif counterparty_inn and counterparty_inn in own_inns:
            reason = "internal_transfer"
        elif not entity_key:
            reason = "unknown_legal_entity"
        elif operation is None:
            reason = "unknown_dds_article"
        elif operation == "exclude":
            reason = "dds_article_excluded"
        row["operation"] = operation
        if operation == "refund":
            row["amount"] = -abs(Decimal(str(row.get("amount") or 0)))
        row["excluded"] = bool(reason)
        row["exclusion_reason"] = reason
        out.append(row)
    return out


def _receipt_identity(row: dict) -> str:
    stable = {
        key: row.get(key)
        for key in (
            "registrar_id",
            "registrar_number",
            "registrar_type",
            "row_number",
            "registrar_date",
            "organization_id",
            "counterparty_id",
            "contract_id",
            "article_id",
            "article_name",
            "amount",
        )
    }
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str)
    return f"1c:{hashlib.sha256(payload.encode()).hexdigest()}"


# ------------------- Лёгкая синхронизация сделок (боевой режим) -------------------

# Поля сделки, которые приходят из Битрикс24 и обновляются при синхронизации.
# Остальное (локальные задачи, история этапов) принадлежит нам и не затирается.
# position сюда не входит: порядок задаётся отдельно (см. refresh_deals).
_DEAL_SYNC_FIELDS = (
    "on_dashboard", "ref", "crm_source", "entity_type", "legal_entity_key",
    "funnel_id", "funnel_name", "name", "src", "campaign", "utm", "mgr", "mgr_id",
    "phone", "client_type", "refuse_reason", "custom", "status_label", "status_class",
    "stage", "amount", "created_at", "last_activity_at", "has_open_action",
)


def _open_action_ids(deals: list[dict], adapter=None) -> set[str]:
    """external_id сделок с открытой задачей/делом в Битрикс24 (best-effort).

    Признак нужен правилу «Сделка без задачи»: без него любая выгруженная сделка
    выглядит как «без задачи». Сбой (нет прав, недоступен портал) не должен ронять
    синхронизацию — тогда признак остаётся пустым, поведение как раньше.
    """
    ids = [str(d.get("external_id")) for d in deals if d.get("external_id")]
    if not ids:
        return set()
    try:
        return (adapter or factory.get_bitrix24()).fetch_open_action_deal_ids(ids)
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
    deals: list[dict], progress: Progress | None = None, adapter=None
) -> tuple[dict, dict, dict, dict]:
    """Справочники сотрудников/стадий/источников и телефоны контактов (best-effort)."""
    b24 = adapter or factory.get_bitrix24()
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
    (Директ/Метрика/1С) не трогаются, тянутся только сделки. По умолчанию
    берутся сделки, изменённые за последнее окно; full=True перечитывает всё окно
    дашборда и убирает сделки, исчезнувшие из портала.

    Строки сделок обновляются на месте (по ID Битрикс24), а не пересоздаются:
    иначе при каждой сверке терялись бы локально поставленные задачи и «сделки
    без задач» возвращались бы в мониторинг сразу после постановки задачи.
    """
    if settings.data_source != "real":
        return {"skipped": True, "reason": "демо-режим", "updated": 0, "created": 0}
    connections = factory.get_bitrix24_connections()
    if not connections:
        return {"skipped": True, "reason": "Битрикс24 не настроен", "updated": 0, "created": 0}

    from app.services.integrations_config import get_field_map
    extra_fields = (await get_field_map(session)).get("fields") or {}

    now = datetime.now(UTC)
    business_config = await business.get_settings(session)
    batches: list[tuple[str, list[dict], tuple[dict, dict, dict, dict], set[str]]] = []
    for source_key, adapter in connections:
        if full:
            window = (now - timedelta(days=_DEALS_WINDOW_DAYS)).strftime(
                "%Y-%m-%dT00:00:00+03:00"
            )
            raw = adapter.fetch_deals(created_after=window, extra_fields=extra_fields)
        else:
            since = (now - timedelta(minutes=_SYNC_OVERLAP_MINUTES)).isoformat(
                timespec="seconds"
            )
            raw = adapter.fetch_deals(modified_after=since, extra_fields=extra_fields)
        for item in raw:
            item["crm_source"] = source_key
        dictionaries = await _bitrix_dictionaries(raw, adapter=adapter)
        batches.append((source_key, raw, dictionaries, _open_action_ids(raw, adapter)))

    existing = {
        (d.crm_source, d.entity_type, d.external_id): d
        for d in (await session.execute(select(Deal))).scalars().all()
        if d.external_id
    }
    created = updated = 0
    # Порядок сделок. При полном чтении окна он задаётся выдачей портала (по дате
    # создания). При частичной сверке позиции существующих строк не трогаем, а
    # новые дописываем в конец: иначе номера столкнулись бы с уже сохранёнными,
    # и порядок таблицы лидов (а с ним и выбор «оригинала» среди дублей) поплыл бы.
    next_position = max((d.position for d in existing.values()), default=-1) + 1
    position = 0
    seen: set[tuple[str, str, str]] = set()
    for source_key, raw, dictionaries, action_ids in batches:
        users, stages, sources_map, phones = dictionaries
        for nd in raw:
            entity_key = business.legal_entity_for_funnel(
                business_config, source_key, str(nd.get("funnel_id") or "0")
            )
            fresh = _deal_from_bitrix(
                position,
                nd,
                users,
                stages,
                phones,
                sources_map,
                has_open_action=str(nd.get("external_id")) in action_ids,
                legal_entity_key=entity_key,
            )
            position += 1
            ext = fresh.external_id
            identity = (fresh.crm_source, fresh.entity_type, ext or "")
            current = existing.get(identity) if ext else None
            if current is None:
                if not full:
                    fresh.position = next_position
                    next_position += 1
                session.add(fresh)
                created += 1
            else:
                _apply_deal_fields(current, fresh)
                if full:
                    current.position = position - 1
                updated += 1
            if ext:
                seen.add(identity)

    removed = 0
    if full:
        # Только при полном чтении окна известно, каких сделок в портале больше нет.
        active_sources = {source_key for source_key, *_ in batches}
        for identity, row in existing.items():
            if identity[0] in active_sources and identity not in seen:
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
    business_config = await business.get_settings(session)

    # Сопоставление пользовательских полей Битрикс (со страницы «Интеграции»).
    from app.services.integrations_config import get_field_map
    field_map = await get_field_map(session)
    extra_fields = field_map.get("fields") or {}

    # 1. Сделки Битрикс24 (за окно дашборда — иначе выгружается вся история портала).
    bitrix_context: dict[str, tuple[dict, dict, dict, dict, set[str]]] = {}
    connections = factory.get_bitrix24_connections()
    if connections:
        since = (datetime.now(UTC) - timedelta(days=_DEALS_WINDOW_DAYS)).strftime(
            "%Y-%m-%dT00:00:00+03:00"
        )
        deals = []
        for source_key, adapter in connections:
            source_deals = await _fetch_source(
                sources,
                f"bitrix_{source_key}",
                f"Bitrix24 ({source_key})",
                lambda adapter=adapter: adapter.fetch_deals(
                    created_after=since, extra_fields=extra_fields
                ),
                progress,
                f"Bitrix24: загрузка {source_key} за {_DEALS_WINDOW_DAYS} дней…",
            )
            for row in source_deals:
                row["crm_source"] = source_key
            deals.extend(source_deals)
            if sources[f"bitrix_{source_key}"]["status"] == "ok":
                dictionaries = await _bitrix_dictionaries(
                    source_deals, progress, adapter=adapter
                )
                bitrix_context[source_key] = (
                    *dictionaries,
                    _open_action_ids(source_deals, adapter),
                )
    else:
        deals = []
        sources["bitrix"] = {"status": "skipped"}

    # 2. Расход Яндекс Директа (для витрины каналов) + поисковые запросы (минус-слова).
    search_queries: list[dict] = []
    direct_costs: list[dict] = []
    metrika_visits: list[dict] = []
    yandex_connections = factory.get_yandex_connections()
    if yandex_connections:
        for entity_key, direct_adapter, metrika_adapter in yandex_connections:
            account_key = entity_key or "legacy"
            costs = await _fetch_source(
                sources,
                f"yandex_direct_{account_key}",
                f"Яндекс Директ ({account_key})",
                direct_adapter.fetch_channels,
                progress,
                f"Яндекс Директ · {account_key}: статистика кампаний…",
            )
            for row in costs:
                row["legal_entity_key"] = entity_key
                row["account_key"] = account_key
            direct_costs.extend(costs)
            try:
                queries = direct_adapter.fetch_search_queries()
                for row in queries:
                    row["legal_entity_key"] = entity_key
                search_queries.extend(queries)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Яндекс Директ (%s): отчёт по запросам недоступен: %s",
                    account_key,
                    exc,
                )
            visits = await _fetch_source(
                sources,
                f"yandex_metrika_{account_key}",
                f"Яндекс Метрика ({account_key})",
                metrika_adapter.fetch_visits,
                progress,
                f"Яндекс Метрика · {account_key}: визиты…",
            )
            for row in visits:
                row["legal_entity_key"] = entity_key
                row["account_key"] = account_key
            metrika_visits.extend(visits)
    else:
        sources["yandex_direct"] = {"status": "skipped"}
        sources["yandex_metrika"] = {"status": "skipped"}

    # 3. Фактические поступления 1С:УНФ. Статьи ДДС сверяются точным
    # наименованием, юрлицо — по ИНН организации из бизнес-настроек.
    if settings.onec_endpoint and settings.onec_username and settings.onec_password:
        date_from = (datetime.now(UTC) - timedelta(days=_DEALS_WINDOW_DAYS)).date().isoformat()
        date_to = datetime.now(UTC).date().isoformat()
        receipt_rows = await _fetch_source(
            sources,
            "onec",
            "1С:УНФ",
            lambda: factory.get_onec().fetch_receipts(date_from, date_to),
            progress,
            f"1С: загрузка поступлений за {_DEALS_WINDOW_DAYS} дней…",
        )
        receipts = classify_receipts(receipt_rows, business_config)
    else:
        receipts = []
        sources["onec"] = {"status": "skipped"}

    # 4. Пересчёт витрин
    if progress:
        await progress("Пересчёт витрин и показателей…")
    channels = aggregate_channels(direct_costs, deals, receipts)
    baseline = baseline_from_receipts(channels, deals, receipts)
    # Клики (Директ) и визиты (Метрика) — для первых шагов сквозной цепочки.
    baseline["clicks"] = float(sum(int(r.get("clicks") or 0) for r in direct_costs))
    baseline["visits"] = float(sum(int(v.get("visits") or 0) for v in metrika_visits))
    minus_words = minus_word_candidates(search_queries)
    budget_recs = budget_recs_from_channels(channels)

    # 5. Запись (сделки + факты 1С + рекламные витрины + базлайны)
    # Сначала удаляем дочерние факты, чтобы FK не мешал обновить сделки.
    await session.execute(delete(OneCReceipt))
    await session.execute(delete(Deal))  # каскадно чистит задачи/историю этапов
    await session.execute(delete(Campaign))
    await session.execute(delete(Channel))
    await session.execute(delete(AdCost))
    await session.execute(delete(Visit))
    await session.execute(delete(Product))  # устаревшая таблица, больше не наполняется
    await session.execute(delete(Baseline))
    # Демо-таблицы без реального источника (менеджеры/рекомендации/минус-слова/
    # демо-история) в боевом режиме держим пустыми — разделы покажут «нет данных».
    from app.services import data_mode
    await data_mode.clear_no_source_tables(session)

    deal_rows: list[Deal] = []
    for i, nd in enumerate(deals):
        source_key = str(nd.get("crm_source") or "primary")
        users, stages, sources_map, phones, action_ids = bitrix_context.get(
            source_key, ({}, {}, {}, {}, set())
        )
        entity_key = business.legal_entity_for_funnel(
            business_config, source_key, str(nd.get("funnel_id") or "0")
        )
        deal = _deal_from_bitrix(
            i, nd, users, stages, phones, sources_map,
            has_open_action=str(nd.get("external_id")) in action_ids,
            legal_entity_key=entity_key,
        )
        deal_rows.append(deal)
        session.add(deal)
    await session.flush()

    by_external_id: dict[str, list[Deal]] = {}
    for deal in deal_rows:
        if deal.external_id:
            by_external_id.setdefault(deal.external_id, []).append(deal)

    for row in receipts:
        external_id = str(row.get("crm_external_id", "")).strip()
        candidates = by_external_id.get(external_id, []) if external_id else []
        entity_key = str(row.get("legal_entity_key", ""))
        entity_type = str(row.get("crm_entity_type", ""))
        if entity_key:
            candidates = [deal for deal in candidates if deal.legal_entity_key == entity_key]
        if entity_type:
            candidates = [deal for deal in candidates if deal.entity_type == entity_type]
        matched = candidates[0] if len(candidates) == 1 else None
        if matched and not row.get("excluded"):
            matched.paid = True
        session.add(
            OneCReceipt(
                external_key=_receipt_identity(row),
                registrar_id=str(row.get("registrar_id", ""))[:128],
                registrar_number=str(row.get("registrar_number", ""))[:64],
                registrar_type=str(row.get("registrar_type", ""))[:64],
                registrar_date=_parse_dt(row.get("registrar_date")),
                legal_entity_key=str(row.get("legal_entity_key", ""))[:32],
                organization_id=str(row.get("organization_id", ""))[:128],
                organization_name=str(row.get("organization_name", ""))[:255],
                organization_inn=str(row.get("organization_inn", ""))[:16],
                counterparty_id=str(row.get("counterparty_id", ""))[:128],
                counterparty_name=str(row.get("counterparty_name", ""))[:255],
                counterparty_inn=str(row.get("counterparty_inn", ""))[:16],
                contract_id=str(row.get("contract_id", ""))[:128],
                contract_number=str(row.get("contract_number", ""))[:128],
                article_id=str(row.get("article_id", ""))[:128],
                article_code=str(row.get("article_code", ""))[:128],
                article_name=str(row.get("article_name", ""))[:255],
                operation=str(row.get("operation") or "income")[:16],
                amount=Decimal(str(row.get("amount") or 0)),
                currency=str(row.get("currency", "RUB"))[:8],
                crm_source=str(row.get("crm_source", ""))[:32],
                crm_entity_type=str(row.get("crm_entity_type", ""))[:16],
                crm_external_id=external_id[:48],
                matched_deal_id=matched.id if matched else None,
                excluded=bool(row.get("excluded")),
                exclusion_reason=str(row.get("exclusion_reason", ""))[:255],
                raw=row.get("raw") or {},
                fetched_at=datetime.now(UTC),
            )
        )

    # Сырьё источников по дням — из него считаются расход/клики/визиты за период
    # (иначе показатели остаются одним 30-дневным итогом на все периоды).
    for row in direct_costs:
        session.add(AdCost(
            legal_entity_key=str(row.get("legal_entity_key") or "")[:32],
            account_key=str(row.get("account_key") or "")[:48],
            date=_parse_date(row.get("date")),
            campaign=str(row.get("campaign") or "")[:128],
            campaign_id=str(row.get("campaign_id") or "")[:32] or None,
            spend=_row_spend_net(row),
            clicks=int(row.get("clicks") or 0),
            impressions=int(row.get("impressions") or 0),
        ))
    for row in metrika_visits:
        session.add(Visit(
            legal_entity_key=str(row.get("legal_entity_key") or "")[:32],
            account_key=str(row.get("account_key") or "")[:48],
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
    stats = {
        "deals": len(deals),
        "channels": len(channels),
        "receipts": len(receipts),
        "receipts_included": sum(1 for row in receipts if not row.get("excluded")),
    }
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
