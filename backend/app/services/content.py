"""AI-инсайты, рекомендации по бюджету, настройки регламента и история изменений."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiInsight, BudgetRec, RegulationConfig, SettingsHistory


async def insights(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(AiInsight).order_by(AiInsight.position))).scalars().all()
    return [
        {
            "sev_label": r.sev_label, "sev_class": r.sev_class, "ic": r.ic, "icon": r.icon,
            "title": r.title, "time": r.time, "surface": r.surface, "text": r.text,
            "rec": r.rec, "src": r.src, "conf": r.conf, "dep": r.dep,
        }
        for r in rows
    ]


async def budget_recs(
    session: AsyncSession, period: str = "30", legal_entity: str = "all",
) -> list[dict]:
    stmt = select(BudgetRec).order_by(BudgetRec.position)
    if legal_entity and legal_entity != "all":
        stmt = stmt.where(BudgetRec.legal_entity_key == legal_entity)
    rows = (await session.execute(stmt)).scalars().all()
    from app.core.config import settings
    if settings.data_source == "real":
        from app.services import channels as channel_service
        from app.services.ingest import budget_recs_from_channels
        current = await channel_service.for_period(
            session, period, legal_entity=legal_entity,
        )
        if current is not None:
            action_rows = rows
            if legal_entity and legal_entity != "all":
                action_rows = (await session.execute(
                    select(BudgetRec).order_by(BudgetRec.position)
                )).scalars().all()
            stored = {(row.legal_entity_key, row.title): row for row in action_rows}
            generated = budget_recs_from_channels(current)
            for item in generated:
                match = stored.get((legal_entity if legal_entity != "all" else "", item["title"]))
                if match is None:
                    match = next((row for row in action_rows if row.title == item["title"]), None)
                item.update(
                    id=match.id if match else 0,
                    status=match.status if match else "new",
                    deferred_until=match.deferred_until if match else None,
                )
            return generated
    return [
        {
            "id": r.id, "ic": r.ic, "svg": r.svg, "title": r.title, "tag_label": r.tag_label,
            "tag_class": r.tag_class, "text": r.text, "why": r.why, "impact": r.impact,
            "src": r.src, "conf": r.conf, "dep": r.dep, "status": r.status,
            "deferred_until": r.deferred_until,
        }
        for r in rows
    ]


async def regulation(session: AsyncSession) -> dict:
    cfg = await session.get(RegulationConfig, 1)
    return cfg.data if cfg else {}


async def history(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(
        select(SettingsHistory).order_by(SettingsHistory.position)
    )).scalars().all()
    return [
        {"id": r.id, "dt": r.dt, "user": r.user, "param": r.param,
         "from": r.value_from, "to": r.value_to, "crit": r.crit,
         "can_rollback": bool(r.path)}
        for r in rows
    ]
