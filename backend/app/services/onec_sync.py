"""Изолированная ночная синхронизация поступлений 1С:УНФ."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations import factory
from app.models import Deal, OneCReceipt
from app.services import business_settings, ingest

logger = get_logger("lawyer.onec_sync")


def _deal_sources_by_entity(config: dict) -> dict[str, set[str]]:
    """Порталы Bitrix24, в которых настроены воронки каждого юрлица."""
    result: dict[str, set[str]] = {}
    for funnel in config.get("funnels", []):
        if not funnel.get("enabled", True):
            continue
        if str(funnel.get("entity_type") or "deal") != "deal":
            continue
        entity_key = str(funnel.get("legal_entity_key") or "").strip()
        source_key = str(funnel.get("crm_source") or "").strip()
        if entity_key and source_key:
            result.setdefault(entity_key, set()).add(source_key)
    return result


def _has_matching_deal(row: dict, by_external_id: dict[str, list[Deal]]) -> bool:
    external_id = str(row.get("crm_external_id") or "").strip()
    if not external_id:
        return False
    candidates = by_external_id.get(external_id, [])
    entity_key = str(row.get("legal_entity_key") or "")
    entity_type = str(row.get("crm_entity_type") or "")
    crm_source = str(row.get("crm_source") or "")
    return any(
        (not entity_key or deal.legal_entity_key == entity_key)
        and (not entity_type or deal.entity_type == entity_type)
        and (not crm_source or deal.crm_source == crm_source)
        for deal in candidates
    )


async def _backfill_missing_deals(
    session: AsyncSession,
    receipts: list[dict],
    config: dict,
    deals: list[Deal],
) -> dict[str, object]:
    """Точечно догружает старые сделки по ссылкам из «Заказа покупателя» 1С."""
    by_external_id: dict[str, list[Deal]] = {}
    for deal in deals:
        if deal.external_id:
            by_external_id.setdefault(str(deal.external_id), []).append(deal)

    missing_by_entity: dict[str, set[str]] = {}
    requested_by_source: dict[str, set[str]] = {}
    source_map = _deal_sources_by_entity(config)
    for row in receipts:
        external_id = str(row.get("crm_external_id") or "").strip()
        entity_key = str(row.get("legal_entity_key") or "").strip()
        if (
            row.get("excluded")
            or str(row.get("crm_entity_type") or "") != "deal"
            or not external_id
            or not entity_key
            or _has_matching_deal(row, by_external_id)
        ):
            continue
        missing_by_entity.setdefault(entity_key, set()).add(external_id)
        source_hint = str(row.get("crm_source") or "").strip()
        candidate_sources = source_map.get(entity_key, set())
        if source_hint:
            candidate_sources = candidate_sources & {source_hint}
        for source_key in candidate_sources:
            requested_by_source.setdefault(source_key, set()).add(external_id)

    connections = dict(factory.get_bitrix24_connections())
    from app.services.integrations_config import get_field_map

    extra_fields = (await get_field_map(session)).get("fields") or {}
    existing_by_identity = {
        (deal.crm_source, deal.entity_type, str(deal.external_id)): deal
        for deal in deals if deal.external_id
    }
    next_position = max((deal.position for deal in deals), default=-1) + 1
    requested = fetched = created = updated = 0
    errors: dict[str, str] = {}

    for source_key, ids in requested_by_source.items():
        adapter = connections.get(source_key)
        if adapter is None:
            errors[source_key] = "Подключение Bitrix24 не настроено"
            continue
        requested += len(ids)
        try:
            rows = adapter.fetch_deals_by_ids(sorted(ids), extra_fields=extra_fields)
        except Exception as exc:  # noqa: BLE001 — поступления всё равно надо обновить
            logger.warning(
                "Bitrix24 (%s): точечная загрузка сделок 1С не удалась: %s",
                source_key,
                exc,
            )
            errors[source_key] = str(exc)
            continue
        fetched += len(rows)
        accepted = []
        for row in rows:
            external_id = str(row.get("external_id") or "").strip()
            entity_key = business_settings.legal_entity_for_funnel(
                config, source_key, str(row.get("funnel_id") or "0")
            )
            if entity_key and external_id in missing_by_entity.get(entity_key, set()):
                accepted.append((row, entity_key))
        if not accepted:
            continue

        normalized_rows = [row for row, _ in accepted]
        users, stages, sources, phones = await ingest._bitrix_dictionaries(
            normalized_rows,
            adapter=adapter,
            manual_users=business_settings.employee_names_for_source(config, source_key),
        )
        for row, entity_key in accepted:
            external_id = str(row.get("external_id") or "")
            identity = (source_key, "deal", external_id)
            fresh = ingest._deal_from_bitrix(
                next_position, row, users, stages, phones, sources,
                legal_entity_key=entity_key,
            )
            fresh.funnel_name = business_settings.funnel_name(
                config, source_key, fresh.funnel_id
            )[:128]
            fresh.invoice = business_settings.stage_is_expected_payment(
                config, source_key, fresh.funnel_id, fresh.stage
            )
            current = existing_by_identity.get(identity)
            if current is None:
                session.add(fresh)
                deals.append(fresh)
                by_external_id.setdefault(external_id, []).append(fresh)
                existing_by_identity[identity] = fresh
                next_position += 1
                created += 1
            else:
                ingest._apply_deal_fields(current, fresh)
                updated += 1

    if created or updated:
        await session.flush()
    logger.info(
        "1С backfill Bitrix24: запрошено=%d получено=%d создано=%d обновлено=%d ошибок=%d",
        requested, fetched, created, updated, len(errors),
    )
    return {
        "requested": requested,
        "fetched": fetched,
        "created": created,
        "updated": updated,
        "errors": errors,
        "without_source_mapping": sorted(set(missing_by_entity) - set(source_map)),
    }


async def sync_onec(session: AsyncSession) -> dict:
    config = await business_settings.get_settings(session)
    date_to = datetime.now(UTC).date().isoformat()
    date_from = (datetime.now(UTC) - timedelta(days=ingest._DEALS_WINDOW_DAYS)).date().isoformat()
    # Сеть вызывается до удаления: при ошибке прежние поступления остаются в БД.
    source_rows = factory.get_onec().fetch_receipts(date_from, date_to)
    receipts = ingest.classify_receipts(source_rows, config)
    deals = (await session.scalars(select(Deal))).all()
    backfill = await _backfill_missing_deals(session, receipts, config, deals)
    by_external_id: dict[str, list[Deal]] = {}
    for deal in deals:
        if deal.external_id:
            by_external_id.setdefault(deal.external_id, []).append(deal)

    await session.execute(delete(OneCReceipt))
    await session.execute(update(Deal).values(paid=False))
    matched_count = 0
    for row in receipts:
        external_id = str(row.get("crm_external_id", "")).strip()
        candidates = by_external_id.get(external_id, []) if external_id else []
        entity_key = str(row.get("legal_entity_key", ""))
        entity_type = str(row.get("crm_entity_type", ""))
        crm_source = str(row.get("crm_source", ""))
        if entity_key:
            candidates = [deal for deal in candidates if deal.legal_entity_key == entity_key]
        if entity_type:
            candidates = [deal for deal in candidates if deal.entity_type == entity_type]
        if crm_source:
            candidates = [deal for deal in candidates if deal.crm_source == crm_source]
        matched = candidates[0] if len(candidates) == 1 else None
        if matched and not row.get("excluded"):
            matched.paid = True
            matched_count += 1
        session.add(OneCReceipt(
            external_key=ingest._receipt_identity(row),
            registrar_id=str(row.get("registrar_id", ""))[:128],
            registrar_number=str(row.get("registrar_number", ""))[:64],
            registrar_type=str(row.get("registrar_type", ""))[:64],
            registrar_date=ingest._parse_dt(row.get("registrar_date")),
            legal_entity_key=entity_key[:32],
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
            crm_entity_type=entity_type[:16],
            crm_external_id=external_id[:48],
            matched_deal_id=matched.id if matched else None,
            excluded=bool(row.get("excluded")),
            exclusion_reason=str(row.get("exclusion_reason", ""))[:255],
            raw=row.get("raw") or {},
            fetched_at=datetime.now(UTC),
        ))
    await session.commit()
    return {
        "rows": len(receipts),
        "included": sum(1 for row in receipts if not row.get("excluded")),
        "excluded": sum(1 for row in receipts if row.get("excluded")),
        "matched_deals": matched_count,
        "deal_backfill": backfill,
    }
