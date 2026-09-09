"""Изолированная синхронизация Яндекс Директа и Метрики.

Не обращается к Bitrix24 и 1С и не изменяет их сырьё. Каждый ресурс обновляется
только после успешной выгрузки; при сетевой/API-ошибке его предыдущие данные
остаются в базе.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.real import RealYandexDirectAdapter, RealYandexMetrikaAdapter
from app.models import (
    AdCost,
    Baseline,
    BudgetRec,
    Campaign,
    Channel,
    Deal,
    MinusWord,
    OneCReceipt,
    Visit,
)
from app.services import ingest, integrations_config

Progress = Callable[[str], Awaitable[None]]


def _resource_key(item: dict, kind: str) -> str:
    """Сохраняет прежние ключи у автоматически мигрированных подключений."""
    item_id = str(item.get("id") or "")
    legacy_prefix = f"legacy-{kind}-"
    if item_id.startswith(legacy_prefix):
        return item_id.removeprefix(legacy_prefix)[:48]
    return item_id[:48]


def _dedupe(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
    """Схлопывает повторные строки одного отчёта по его естественному ключу."""
    result: dict[tuple[str, ...], dict] = {}
    for row in rows:
        key = tuple(str(row.get(field) or "") for field in fields)
        current = result.get(key)
        if current is None:
            result[key] = dict(row)
            continue
        for metric in ("spend_gross", "spend", "clicks", "impressions", "visits"):
            if metric in row:
                current[metric] = int(current.get(metric) or 0) + int(row.get(metric) or 0)
    return list(result.values())


async def _progress(callback: Progress | None, text: str) -> None:
    if callback:
        await callback(text)


async def sync_yandex(
    session: AsyncSession, progress: Progress | None = None
) -> dict:
    config = await integrations_config.get_yandex_config(session, masked=False)
    credentials = {
        item["id"]: item for item in config["credentials"]
        if item.get("enabled", True) and item.get("token")
    }
    configured_direct = [
        item for item in config["direct_accounts"]
        if item.get("enabled", True)
    ]
    configured_counters = [
        item for item in config["metrika_counters"]
        if item.get("enabled", True)
    ]
    direct_accounts = [
        item for item in configured_direct if item.get("credential_id") in credentials
    ]
    counters = [
        item for item in configured_counters if item.get("credential_id") in credentials
    ]
    sources: dict[str, dict] = {}
    direct_updates: dict[str, list[dict]] = {}
    visit_updates: dict[str, list[dict]] = {}
    search_queries: list[dict] = []

    for item in configured_direct:
        if item.get("credential_id") not in credentials:
            key = _resource_key(item, "direct")
            sources[f"yandex_direct_{key}"] = {
                "status": "error", "message": "OAuth-токен не задан или доступ отключён.",
                "label": item.get("name") or key, "retained_previous": True,
            }
    for item in configured_counters:
        if item.get("credential_id") not in credentials:
            key = _resource_key(item, "metrika")
            sources[f"yandex_metrika_{key}"] = {
                "status": "error", "message": "OAuth-токен не задан или доступ отключён.",
                "label": item.get("name") or key, "retained_previous": True,
            }

    for item in direct_accounts:
        key = _resource_key(item, "direct")
        label = item.get("name") or item.get("client_login") or key
        await _progress(progress, f"Директ · {label}: расходы и кампании…")
        credential = credentials[item["credential_id"]]
        adapter = RealYandexDirectAdapter(
            oauth_token=credential["token"],
            direct_login=str(item.get("client_login") or ""),
        )
        source_key = f"yandex_direct_{key}"
        try:
            rows = adapter.fetch_channels()
            for row in rows:
                row["legal_entity_key"] = item.get("legal_entity_key") or ""
                row["account_key"] = key
            rows = _dedupe(rows, ("date", "campaign_id", "campaign"))
            direct_updates[key] = rows
            sources[source_key] = {"status": "ok", "count": len(rows), "label": label}
            try:
                queries = adapter.fetch_search_queries()
                for row in queries:
                    row["legal_entity_key"] = item.get("legal_entity_key") or ""
                search_queries.extend(queries)
            except Exception as exc:  # noqa: BLE001
                sources[source_key]["status"] = "partial"
                sources[source_key]["message"] = f"Расходы загружены; поисковые запросы: {exc}"
        except Exception as exc:  # noqa: BLE001
            sources[source_key] = {
                "status": "error", "message": str(exc), "label": label,
                "retained_previous": True,
            }

    for item in counters:
        key = _resource_key(item, "metrika")
        label = item.get("name") or item.get("counter_id") or key
        await _progress(progress, f"Метрика · {label}: визиты…")
        credential = credentials[item["credential_id"]]
        adapter = RealYandexMetrikaAdapter(
            oauth_token=credential["token"], counter_id=str(item.get("counter_id") or "")
        )
        source_key = f"yandex_metrika_{key}"
        try:
            rows = adapter.fetch_visits()
            for row in rows:
                row["legal_entity_key"] = item.get("legal_entity_key") or ""
                row["account_key"] = key
            rows = _dedupe(rows, ("date", "source"))
            visit_updates[key] = rows
            sources[source_key] = {"status": "ok", "count": len(rows), "label": label}
        except Exception as exc:  # noqa: BLE001
            sources[source_key] = {
                "status": "error", "message": str(exc), "label": label,
                "retained_previous": True,
            }

    configured_direct_keys = {_resource_key(item, "direct") for item in configured_direct}
    configured_counter_keys = {_resource_key(item, "metrika") for item in configured_counters}
    # Удалённые/отключённые ресурсы больше не участвуют в аналитике.
    if configured_direct_keys:
        await session.execute(
            delete(AdCost).where(AdCost.account_key.not_in(configured_direct_keys))
        )
    else:
        await session.execute(delete(AdCost))
    if configured_counter_keys:
        await session.execute(
            delete(Visit).where(Visit.account_key.not_in(configured_counter_keys))
        )
    else:
        await session.execute(delete(Visit))

    for key, rows in direct_updates.items():
        await session.execute(delete(AdCost).where(AdCost.account_key == key))
        for row in rows:
            session.add(AdCost(
                legal_entity_key=str(row.get("legal_entity_key") or "")[:32],
                account_key=key,
                date=ingest._parse_date(row.get("date")),
                campaign=str(row.get("campaign") or "")[:128],
                campaign_id=str(row.get("campaign_id") or "")[:32] or None,
                spend=ingest._row_spend_net(row),
                clicks=int(row.get("clicks") or 0),
                impressions=int(row.get("impressions") or 0),
            ))
    for key, rows in visit_updates.items():
        await session.execute(delete(Visit).where(Visit.account_key == key))
        for row in rows:
            session.add(Visit(
                legal_entity_key=str(row.get("legal_entity_key") or "")[:32],
                account_key=key,
                date=ingest._parse_date(row.get("date")),
                source=str(row.get("source") or "")[:128],
                visits=int(row.get("visits") or 0),
            ))
    await session.flush()

    # Пересобираем только маркетинговые витрины из нового/сохранённого сырья.
    costs = [
        {
            "date": row.date, "campaign_id": row.campaign_id,
            "campaign": row.campaign, "spend": row.spend,
            "clicks": row.clicks, "impressions": row.impressions,
            "legal_entity_key": row.legal_entity_key, "account_key": row.account_key,
        }
        for row in (await session.scalars(select(AdCost))).all()
    ]
    deals = [
        {
            "external_id": row.external_id, "campaign": row.campaign,
            "amount": row.amount, "stage": row.stage, "invoice": row.invoice,
            "custom": row.custom or {},
        }
        for row in (await session.scalars(select(Deal))).all()
    ]
    receipts = [
        {"crm_external_id": row.crm_external_id, "amount": row.amount,
         "excluded": row.excluded}
        for row in (await session.scalars(select(OneCReceipt))).all()
    ]
    visits = (await session.scalars(select(Visit))).all()
    channels = ingest.aggregate_channels(costs, deals, receipts)
    baseline = ingest.baseline_from_receipts(channels, deals, receipts)
    saved_costs = (await session.scalars(select(AdCost))).all()
    baseline["clicks"] = float(sum(row.clicks for row in saved_costs))
    baseline["visits"] = float(sum(row.visits for row in visits))

    await session.execute(delete(Campaign))
    await session.execute(delete(Channel))
    await session.execute(delete(Baseline))
    for index, item in enumerate(channels):
        channel = Channel(
            position=index, name=item["name"], color=item["color"], spend=item["spend"],
            leads=item["leads"], deals=item["deals"], payments=item["payments"],
            revenue=item["revenue"], margin=item["margin"],
        )
        for position, campaign in enumerate(item["campaigns"]):
            channel.campaigns.append(Campaign(
                position=position, name=campaign["name"], spend=campaign["spend"],
                leads=campaign["leads"], deals=campaign["deals"],
                payments=campaign["payments"], revenue=campaign["revenue"],
                margin=campaign["margin"],
            ))
        session.add(channel)
    for key, value in baseline.items():
        session.add(Baseline(key=key, value=value))

    if direct_updates:
        await session.execute(delete(MinusWord))
        await session.execute(delete(BudgetRec))
        for index, item in enumerate(ingest.minus_word_candidates(search_queries)):
            session.add(MinusWord(
                position=index, phrase=item["phrase"], camp=item["camp"],
                shows=item["shows"], clicks=item["clicks"], spend=item["spend"],
                conv=0, deals=0, reason=item["reason"], status="new",
            ))
        for index, item in enumerate(ingest.budget_recs_from_channels(channels)):
            session.add(BudgetRec(
                position=index, ic=item["ic"], svg=item["svg"], title=item["title"],
                tag_label=item["tag_label"], tag_class=item["tag_class"], text=item["text"],
                why=item["why"], impact=item["impact"], src=item["src"], conf=item["conf"],
                dep=item["dep"],
            ))

    await session.commit()
    errors = sum(1 for item in sources.values() if item.get("status") == "error")
    return {
        "mode": "real", "sources": sources,
        "stats": {
            "direct_rows": sum(len(rows) for rows in direct_updates.values()),
            "visit_rows": sum(len(rows) for rows in visit_updates.values()),
            "updated_resources": len(direct_updates) + len(visit_updates),
            "retained_failed_resources": errors,
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    }
