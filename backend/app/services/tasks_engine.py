"""Логика создания задач ответственным (триггер · адресат · текст · срок).

Формирует задачу по нарушению регламента согласно настройке «Логика создания
задач» (task_logic). Постановка в Битрикс24 выполняется через адаптер (мок в dev,
боевой на Этапе E) — требует прав на запись задач.
"""

from __future__ import annotations

from datetime import timedelta

from app.models import Deal
from app.services.clock import reference_now


def resolve_assignee(deal: Deal, task_logic: dict) -> str:
    mode = task_logic.get("assignee", "Ответственный по сделке")
    responsible = deal.mgr if deal.mgr and deal.mgr != "—" else "Руководитель ОП"
    if mode == "Руководитель отдела продаж":
        return "Руководитель ОП"
    if mode == "Ответственный + руководитель":
        return f"{responsible} + Руководитель ОП"
    return responsible


def render_text(deal: Deal, template: str, due_label: str) -> str:
    return (
        template.replace("{этап}", deal.stage or "—")
        .replace("{сделка}", deal.ref or deal.name)
        .replace("{клиент}", deal.name)
        .replace("{срок}", due_label)
    )


def build_task(
    deal: Deal,
    config: dict,
    head_id: str | None = None,
    head_name: str | None = None,
) -> dict:
    """Готовит параметры задачи: адресат, текст, срок."""
    task_logic = config.get("task_logic", {})
    template = task_logic.get("template", "Свяжитесь по сделке {сделка} и обновите статус.")
    due_at = reference_now() + timedelta(days=1)
    due_label = due_at.strftime("%d.%m %H:%M")
    mode = task_logic.get("assignee", "Ответственный по сделке")
    assignee_id = head_id if mode == "Руководитель отдела продаж" and head_id else deal.mgr_id
    accomplice_ids = (
        [head_id] if mode == "Ответственный + руководитель" and head_id and head_id != deal.mgr_id
        else []
    )
    return {
        "assignee": (
            head_name
            if mode == "Руководитель отдела продаж" and head_name
            else resolve_assignee(deal, task_logic)
        ),
        "assignee_id": assignee_id,
        "accomplice_ids": accomplice_ids,
        "deal_external_id": deal.external_id,
        "title": render_text(deal, template, due_label),
        "due_at": due_at,
        "due_label": due_label,
    }
