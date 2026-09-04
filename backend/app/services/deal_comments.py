"""Построчные комментарии по сделкам: фактическая база + опциональное LLM-уточнение."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import client as llm
from app.ai.prompts import SYSTEM_PROMPT
from app.models import Deal
from app.services import violations as vio

_PRIORITY = {"over": 0, "review": 1, "warn": 2}


def _deal_key(deal: Deal) -> str:
    return f"{deal.crm_source}:{deal.entity_type}:{deal.external_id or deal.id}"


def _baseline_comment(deal: Deal, issues: list[dict]) -> str:
    if issues:
        ordered = sorted(issues, key=lambda row: _PRIORITY.get(str(row.get("severity")), 9))
        comments = []
        for issue in ordered:
            text = str(issue.get("ai") or issue.get("kind_label") or "").strip()
            if text and text not in comments:
                comments.append(text.rstrip("."))
            if len(comments) == 2:
                break
        if comments:
            return (". ".join(comments) + ".")[:500]
    if deal.status_class == "st-ok":
        return "Сделка успешно завершена; отклонений от регламента не выявлено."
    if deal.status_class == "st-bad":
        return "Сделка закрыта; проверьте, что итог и причина отказа зафиксированы корректно."
    stage = str(deal.stage or deal.status_label or "текущий этап").strip()
    return f"Отклонений от регламента не выявлено; продолжайте работу по этапу «{stage}»."[:500]


async def refresh_baseline(session: AsyncSession) -> dict[str, int]:
    """Обновляет комментарии из текущих фактов CRM; не требует внешнего AI."""
    evaluated = await vio.evaluate_current(session)
    by_deal: dict[str, list[dict]] = {}
    for issue in [*evaluated.get("regular", []), *evaluated.get("review", [])]:
        by_deal.setdefault(str(issue.get("deal_key") or ""), []).append(issue)
    deals = list((await session.execute(select(Deal))).scalars().all())
    changed = 0
    for deal in deals:
        comment = _baseline_comment(deal, by_deal.get(_deal_key(deal), []))
        fingerprint = hashlib.sha256(comment.encode()).hexdigest()
        if (
            deal.ai_comment_source == "llm"
            and deal.ai_comment_fingerprint == fingerprint
            and deal.ai_comment
        ):
            continue
        if deal.ai_comment != comment:
            deal.ai_comment = comment
            changed += 1
        deal.ai_comment_source = "baseline"
        deal.ai_comment_fingerprint = fingerprint
    await session.commit()
    return {"count": len(deals), "changed": changed}


def _parse_comments(raw: str) -> list[dict]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1]
    start, end = text.find("["), text.rfind("]")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


async def generate_with_llm(
    session: AsyncSession, batch_size: int = 40, max_deals: int = 40
) -> dict:
    """Уточняет базовые комментарии пакетами без передачи контактов и сумм."""
    baseline = await refresh_baseline(session)
    if not llm.is_configured():
        return {"generated": False, "reason": "llm_not_configured", **baseline}

    deals = list((await session.execute(
        select(Deal)
        .where(Deal.on_dashboard.is_(True))
        .order_by(Deal.position.desc())
        .limit(max_deals)
    )).scalars().all())
    client = llm.LLMClient()
    generated = 0
    system = (
        SYSTEM_PROMPT
        + " Комментируй работу по конкретным сделкам. Не придумывай факты. "
        "Верни только валидный JSON-массив."
    )
    for offset in range(0, len(deals), batch_size):
        batch = deals[offset:offset + batch_size]
        payload = [
            {
                "id": deal.id,
                "stage": deal.stage or deal.status_label,
                "first_contact": deal.first_contact,
                "call_recorded": deal.call,
                "invoice_recorded": deal.invoice,
                "payment_recorded": deal.paid,
                "has_open_action": deal.has_open_action,
                "current_comment": deal.ai_comment,
            }
            for deal in batch
        ]
        prompt = (
            "Для каждой переданной сделки дай одно короткое практическое предложение "
            "о риске или следующем действии. Сохрани id без изменений. Формат: "
            '[{"id": 123, "comment": "..."}]. Данные:\n'
            + json.dumps(payload, ensure_ascii=False, default=str)
        )
        items = _parse_comments(client.complete(system, prompt))
        by_id = {
            int(item["id"]): " ".join(str(item.get("comment") or "").split())[:500]
            for item in items
            if str(item.get("id") or "").isdigit() and item.get("comment")
        }
        allowed = {deal.id for deal in batch}
        for deal in batch:
            comment = by_id.get(deal.id)
            if deal.id in allowed and comment:
                deal.ai_comment = comment
                deal.ai_comment_source = "llm"
                generated += 1
    await session.commit()
    return {"generated": True, "count": generated, "baseline_count": baseline["count"]}
