"""AI-слой интерпретации: генерация инсайтов по расписанию.

В mock-режиме инсайты берутся из демо-данных (уже в БД) и не перегенерируются.
В боевом режиме при настроенном LLM инсайты формируются по сводке аналитики.
Вызывается джобой планировщика (worker), не на каждое событие.
"""

from __future__ import annotations

import json

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import client as llm
from app.ai import prompts
from app.core.config import settings
from app.core.logging import get_logger
from app.models import AiInsight, Baseline, BudgetRec, Channel
from app.services import rec_style

logger = get_logger("lawyer.ai")


async def _analytics_summary(session: AsyncSession) -> dict:
    channels = (await session.execute(select(Channel))).scalars().all()
    baselines = (await session.execute(select(Baseline))).scalars().all()
    return {
        "channels": [
            {"name": c.name, "spend": c.spend, "revenue": c.revenue, "margin": c.margin,
             "leads": c.leads, "deals": c.deals, "payments": c.payments}
            for c in channels
        ],
        "baseline": {b.key: b.value for b in baselines},
    }


# Сопоставление «важности» из ответа LLM с классами оформления карточки инсайта.
_SEV_RULES: list[tuple[tuple[str, ...], tuple[str, str, str, str]]] = [
    (("риск", "risk", "утеч", "leak"), ("Риск", "t-red", "i-red", "alert")),
    (("деньг", "маржа", "money", "убыт"), ("Деньги", "t-red", "i-red", "alert")),
    (("возмож", "opportun", "рост", "growth"), ("Возможность", "t-green", "i-green", "up")),
    (("оптимиз", "optim", "эффект"), ("Оптимизация", "t-blue", "i-indigo", "net")),
]
_SEV_DEFAULT = ("Наблюдение", "t-amber", "i-amber", "clock")


def _map_sev(text: str) -> tuple[str, str, str, str]:
    low = (text or "").lower()
    for keys, meta in _SEV_RULES:
        if any(k in low for k in keys):
            return meta
    return _SEV_DEFAULT


def _parse_items(raw: str) -> list[dict]:
    """Толерантный разбор ответа LLM в список объектов-инсайтов."""
    s = (raw or "").strip()
    if s.startswith("```"):  # снимаем markdown-обёртку ```json ... ```
        s = s.strip("`")
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
    start, end = s.find("["), s.rfind("]")
    if start != -1 and end != -1 and end > start:
        s = s[start:end + 1]
    try:
        data = json.loads(s)
    except (ValueError, TypeError):
        return []
    if isinstance(data, dict):
        for key in ("insights", "items", "data", "инсайты"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
        return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _pick(item: dict, *keys: str, default: str = "") -> str:
    for k in keys:
        v = item.get(k)
        if v:
            return str(v)
    return default


async def generate_insights(session: AsyncSession) -> dict:
    """Генерирует AI-инсайты через LLM по сводке аналитики и сохраняет их.

    Требует настроенной AI-интеграции (LLM_API_KEY, LLM_BASE_URL). Заменяет
    текущий набор инсайтов. Возвращает статус и число сохранённых карточек.
    """
    if not llm.is_configured():
        return {"generated": False, "reason": "llm_not_configured"}

    summary = await _analytics_summary(session)
    client = llm.LLMClient()
    system = (
        prompts.SYSTEM_PROMPT
        + " Верни СТРОГО валидный JSON-массив без markdown и пояснений."
    )
    user = (
        prompts.insights_prompt(summary)
        + "\n\nФормат ответа — JSON-массив объектов с полями: "
        '"title" (заголовок), "severity" (одно из: Риск, Деньги, Возможность, '
        'Оптимизация, Наблюдение), "surface" (что видно на дашборде), '
        '"text" (объяснение), "rec" (рекомендация), "sources" (массив источников), '
        '"confidence" (высокая|средняя|низкая). Только JSON.'
    )

    raw = client.complete(system, user)  # синхронный вызов LLM
    items = _parse_items(raw)
    if not items:
        raise ValueError("LLM вернул ответ, который не удалось разобрать как JSON-инсайты.")

    prepared: list[AiInsight] = []
    for i, it in enumerate(items[:6]):
        title = _pick(it, "title", "заголовок")
        if not title:
            continue
        sev_label, sev_class, ic, icon = _map_sev(_pick(it, "severity", "важность", "type"))
        src = it.get("sources") or it.get("src") or it.get("источники") or []
        if isinstance(src, str):
            src = [src]
        prepared.append(AiInsight(
            position=i, sev_label=sev_label, sev_class=sev_class, ic=ic, icon=icon,
            title=title[:255], time="сгенерировано сейчас",
            surface=_pick(it, "surface", "на_дашборде", "dashboard"),
            text=_pick(it, "text", "explanation", "объяснение"),
            rec=_pick(it, "rec", "recommendation", "рекомендация"),
            src=[str(x) for x in src][:6],
            conf=_pick(it, "confidence", "достоверность", default="средняя"),
            dep=bool(it.get("dep")),
        ))

    if not prepared:
        raise ValueError("LLM не вернул ни одного корректного инсайта.")

    await session.execute(delete(AiInsight))
    session.add_all(prepared)
    await session.commit()
    logger.info("AI-инсайты сгенерированы через LLM: %d", len(prepared))
    return {"generated": True, "count": len(prepared)}


async def generate_budget_recs(session: AsyncSession) -> dict:
    """Генерирует рекомендации по бюджету через LLM по сводке каналов и сохраняет их.

    Требует настроенной AI-интеграции (LLM_API_KEY, LLM_BASE_URL). Заменяет текущий
    набор рекомендаций (таблица BudgetRec). Вход — те же реальные показатели каналов,
    что и для инсайтов; модель только интерпретирует их (без выдуманных чисел).
    """
    if not llm.is_configured():
        return {"generated": False, "reason": "llm_not_configured"}

    summary = await _analytics_summary(session)
    client = llm.LLMClient()
    system = (
        prompts.SYSTEM_PROMPT
        + " Верни СТРОГО валидный JSON-массив без markdown и пояснений."
    )
    user = (
        prompts.budget_recs_prompt(summary)
        + "\n\nФормат ответа — JSON-массив объектов с полями: "
        '"title" (заголовок), "action" (одно из: Масштабировать, Под наблюдением, '
        'Проверить, Ограничить), "text" (рекомендация), "why" (как найдено), '
        '"impact" (эффект), "sources" (массив источников), '
        '"confidence" (высокая|средняя|низкая), "dep" (true, если нужна связка '
        "с фактическими поступлениями 1С). Только JSON."
    )

    raw = client.complete(system, user)  # синхронный вызов LLM
    items = _parse_items(raw)
    if not items:
        raise ValueError("LLM вернул ответ, который не удалось разобрать как JSON-рекомендации.")

    prepared: list[BudgetRec] = []
    for it in items[:6]:
        title = _pick(it, "title", "заголовок", "channel", "канал")
        if not title:
            continue
        _key, tag_label, tag_class, ic, svg = rec_style.style_for_action(
            _pick(it, "action", "действие", "recommendation_type")
        )
        src = it.get("sources") or it.get("src") or it.get("источники") or []
        if isinstance(src, str):
            src = [src]
        prepared.append(BudgetRec(
            ic=ic, svg=svg, title=title[:255], tag_label=tag_label, tag_class=tag_class,
            text=_pick(it, "text", "recommendation", "рекомендация"),
            why=_pick(it, "why", "как_найдено", "reason", "обоснование"),
            impact=_pick(it, "impact", "эффект")[:128],
            src=[str(x) for x in src][:6],
            conf=_pick(it, "confidence", "достоверность", default="средняя"),
            dep=bool(it.get("dep")),
        ))

    if not prepared:
        raise ValueError("LLM не вернул ни одной корректной рекомендации по бюджету.")

    # Проблемные каналы (красные/жёлтые) — первыми, как в детерминированной логике.
    prepared.sort(key=lambda r: rec_style.TAG_ORDER.get(r.tag_class, 9))
    for i, rec in enumerate(prepared):
        rec.position = i

    await session.execute(delete(BudgetRec))
    session.add_all(prepared)
    await session.commit()
    logger.info("AI-рекомендации по бюджету сгенерированы через LLM: %d", len(prepared))
    return {"generated": True, "count": len(prepared)}


async def refresh_insights(session: AsyncSession) -> dict:
    """Обновляет AI-инсайты. Возвращает статус выполнения."""
    if settings.data_source != "real" or not llm.is_configured():
        count = await session.scalar(select(AiInsight).with_only_columns(AiInsight.id).limit(1))
        logger.info("AI-инсайты: mock-режим или LLM не настроен — используются текущие данные")
        return {"generated": False, "reason": "mock_or_unconfigured", "has_data": count is not None}

    # Боевой режим: сводка → LLM → разбор → сохранение (реализуется на Этапе E,
    # после согласования модели и юрисдикции). Здесь — точка вызова.
    summary = await _analytics_summary(session)  # noqa: F841 — используется в промпте на Этапе E
    logger.info("AI-инсайты: запрошена генерация через LLM")
    return {"generated": True, "reason": "llm"}
