"""Мониторинг: статистика, список нарушений, оценочные на ревью.

Нарушения вычисляются движком регламента на лету (app.services.reglament),
поэтому изменение порогов в админ-панели немедленно меняет результат.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.integrations import factory
from app.models import Deal, Task
from app.services import content, tasks_engine
from app.services import format as f
from app.services import violations as vio


def _with_amount_display(items: list[dict]) -> list[dict]:
    for v in items:
        v["amount_display"] = f.money(v["amount"]) if v["amount"] else ""
    return items


async def stats(
    session: AsyncSession,
    mgr: str | list[str] = "all",
    hide_financial: bool = False,
) -> dict:
    res = await vio.evaluate_current(session, mgr=mgr)
    regular = res["regular"]
    review = res["review"]
    over = [v for v in regular if v["severity"] == "over"]
    warn = [v for v in regular if v["severity"] == "warn"]
    money = vio.money_at_risk(regular, await vio.risk_amount_cap(session))

    # «В норме» — доля сделок без нарушений (движок выдаёт не более одного
    # нарушения на сделку, поэтому len(regular) ≈ число проблемных сделок).
    total_stmt = select(func.count()).select_from(Deal)
    if mgr != "all":
        total_stmt = total_stmt.where(
            Deal.mgr.in_(mgr) if isinstance(mgr, list) else Deal.mgr == mgr
        )
    total = await session.scalar(total_stmt) or 0
    if total:
        norm = f"{round(max(total - len(regular), 0) / total * 100)}%"
    else:
        norm = "—"

    # key — идентификатор фильтра списка нарушений: клик по плашке ставит ?sev=key.
    # У «В норме» key пуст: это доля сделок без нарушений, показывать в списке нечего.
    stat_rows = [
        {"n": str(len(over)), "label": "Критичные просрочки", "cls": "r", "key": "over"},
        {"n": f.money_short(money), "label": "Деньги под риском", "cls": "r", "key": "money"},
        {"n": str(len(warn)), "label": "Требуют внимания", "cls": "a", "key": "warn"},
        {"n": str(len(review)), "label": "На проверке", "cls": "v", "key": "review"},
        {"n": norm, "label": "В норме", "cls": "g", "key": ""},
    ]
    if hide_financial:
        stat_rows = [row for row in stat_rows if row["key"] != "money"]
    return {"stats": stat_rows, "badge": len(regular)}


async def violations(
    session: AsyncSession, ptype: str | None = None, mgr: str | list[str] = "all",
    hide_financial: bool = False,
) -> list[dict]:
    res = await vio.evaluate_current(session, mgr=mgr)
    regular = res["regular"]
    if ptype:
        regular = [v for v in regular if v["ptype"] == ptype]
    result = _with_amount_display(regular)
    if hide_financial:
        for row in result:
            row.update(amount=0, amount_display="Скрыто")
    return result


async def review(
    session: AsyncSession, mgr: str | list[str] = "all", hide_financial: bool = False,
) -> list[dict]:
    res = await vio.evaluate_current(session, mgr=mgr)
    result = _with_amount_display(res["review"])
    if hide_financial:
        for row in result:
            row.update(amount=0, amount_display="Скрыто")
    return result


async def create_task_for(
    session: AsyncSession, ref: str | None = None, deal_key: str | None = None,
    mgr: str | list[str] = "all",
) -> dict:
    """Ставит задачу ответственному по сделке (по согласованной логике)."""
    # Доступы и режим источника данных сохраняются через UI в БД, а процессов
    # API несколько (gunicorn workers): тот, который не обрабатывал сохранение,
    # оставался с прежним settings.data_source и уходил в мок-адаптер — задача
    # «создавалась» только на экране. Поэтому читаем актуальные настройки из БД.
    from app.services.integrations_config import apply_overrides_from_db
    await apply_overrides_from_db(session)

    stmt = select(Deal).options(selectinload(Deal.tasks))
    if deal_key:
        try:
            crm_source, entity_type, external_id = deal_key.split(":", 2)
        except ValueError as exc:
            raise ValueError("Некорректный идентификатор сделки") from exc
        stmt = stmt.where(
            Deal.crm_source == crm_source,
            Deal.entity_type == entity_type,
            Deal.external_id == external_id,
        )
    elif ref:
        stmt = stmt.where(Deal.ref == ref)
    else:
        raise ValueError("Не указан идентификатор сделки")
    if mgr != "all":
        stmt = stmt.where(Deal.mgr.in_(mgr) if isinstance(mgr, list) else Deal.mgr == mgr)
    deal = (await session.execute(stmt)).scalars().first()
    if deal is None:
        raise ValueError("Сделка не найдена")

    config = await content.regulation(session)
    params = tasks_engine.build_task(deal, config)

    # Постановка в Битрикс24. Ошибка адаптера (нет ответственного, отказ портала,
    # сеть) пробрасывается наверх — локальную задачу при этом НЕ фиксируем, чтобы
    # интерфейс не показывал ложный успех, когда в Битриксе задача не создана.
    adapter = factory.get_bitrix24_connection(deal.crm_source)
    result = await run_in_threadpool(adapter.create_task, {
        "deal_ref": deal.ref, "deal_external_id": deal.external_id,
        "title": params["title"], "assignee": params["assignee"],
        "assignee_id": params["assignee_id"], "due_at": params["due_at"],
    })
    # Мок-адаптер в портал ничего не пишет. Демо-режим — штатный сценарий, но
    # выдавать его за созданную задачу нельзя: отдаём признак mock, и интерфейс
    # сообщает, что задача записана только локально.
    demo = bool(result.get("mock"))
    # Исполнителя назначает портал (ответственный по сделке на текущий момент),
    # поэтому подтверждаем именно его, а не имя из последней выгрузки.
    assignee = result.get("assignee") or params["assignee"]
    deal.tasks.append(Task(
        title=params["title"], assignee=assignee,
        status="open", due_at=params["due_at"],
    ))
    await session.commit()
    return {
        "ok": True, "deal": deal.name, "ref": deal.ref,
        "assignee": assignee, "title": params["title"], "due": params["due_label"],
        "external_id": result.get("external_id"),
        "activity_id": result.get("activity_id"),
        "mock": demo,
    }
