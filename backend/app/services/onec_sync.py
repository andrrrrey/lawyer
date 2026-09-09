"""Изолированная ночная синхронизация поступлений 1С:УНФ."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import factory
from app.models import Deal, OneCReceipt
from app.services import business_settings, ingest


async def sync_onec(session: AsyncSession) -> dict:
    config = await business_settings.get_settings(session)
    date_to = datetime.now(UTC).date().isoformat()
    date_from = (datetime.now(UTC) - timedelta(days=ingest._DEALS_WINDOW_DAYS)).date().isoformat()
    # Сеть вызывается до удаления: при ошибке прежние поступления остаются в БД.
    source_rows = factory.get_onec().fetch_receipts(date_from, date_to)
    receipts = ingest.classify_receipts(source_rows, config)
    deals = (await session.scalars(select(Deal))).all()
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
        if entity_key:
            candidates = [deal for deal in candidates if deal.legal_entity_key == entity_key]
        if entity_type:
            candidates = [deal for deal in candidates if deal.entity_type == entity_type]
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
    }
