"""Сквозная аналитика: цепочка, таблица каналов/кампаний, графики ROMI, минус-слова."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import Channel, MinusWord
from app.seeds.chain import CHAIN_STEPS
from app.services import channels as ch_svc
from app.services import format as f


def _digits(text: str) -> int:
    d = "".join(ch for ch in text if ch.isdigit())
    return int(d) if d else 0


def _has_num(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


async def chain(
    session: AsyncSession, period: str, legal_entity: str = "all"
) -> list[dict]:
    from app.services import metrics
    base, m = await metrics._base_and_mult(
        session, period, legal_entity=legal_entity
    )
    real = settings.data_source == "real"

    steps: list[dict] = []
    for s in CHAIN_STEPS:
        if not real and "static" in s:
            # Демо: статичные клики/визиты из прототипа.
            display = s["static"]
        elif "base_key" in s:
            # Боевой режим: реальное значение (клики — Директ, визиты — Метрика).
            raw = base.get(s["base_key"], 0) * m
            display = f.money_short(raw) if s.get("kind") == "money" else f.fmt(raw)
        else:
            display = "нет данных"
        steps.append({
            "label": s["label"], "sub": s["sub"], "color": s["color"],
            "width": s["width"], "glow": s.get("glow", False), "display": display,
        })

    # Конверсия между шагами — только когда у обоих соседних шагов есть числа.
    for i, step in enumerate(steps):
        if i == 0 or not _has_num(steps[i - 1]["display"]) or not _has_num(step["display"]):
            step["conversion"] = None
        else:
            prev = _digits(steps[i - 1]["display"]) or 1
            step["conversion"] = round(_digits(step["display"]) / prev * 100)
    return steps


async def _channels(session: AsyncSession) -> list[Channel]:
    return list((await session.execute(
        select(Channel).options(selectinload(Channel.campaigns)).order_by(Channel.position)
    )).scalars().all())


def _spend_display(spend: int | None) -> str:
    if spend is None:
        return "нет данных"
    if spend == 0:
        return "0 ₽"
    return f.money(spend)


def _row(name: str, spend: int | None, leads: int, deals: int, payments: int,
         revenue: int, margin: int, *, campaign: bool = False,
         static: bool = True) -> dict:
    """Строка сводки (канал или кампания) с готовыми к выводу значениями.

    У кампаний нулевой/неизвестный расход показывается прочерком (как в прототипе),
    у каналов — развёрнуто («0 ₽» для бесплатного канала, «нет данных» без источника).

    static=False — цифры реальные (пересобраны за период): рекомендуемое действие
    считается из фактического ROMI, а не берётся из сидовых подписей ACTIONS.
    """
    return {
        "name": name, "spend": spend,
        "spend_display": (f.money(spend) if spend else "—") if campaign
                         else _spend_display(spend),
        "leads": leads, "deals": deals, "payments": payments,
        "revenue": revenue, "revenue_display": f.money(revenue),
        "margin": margin, "margin_display": f.money(margin),
        "romi": f.romi_tag(spend, margin),
        "action": f.action_of(name, spend, margin, static=static),
    }


async def _stored_table(session: AsyncSession) -> list[dict]:
    """Сводка из сохранённых витрин (демо-режим и данные до посуточной выгрузки)."""
    # Сидовые подписи ACTIONS верны только для демо-цифр; в боевом режиме
    # (сохранённые итоги реальных источников) действие считаем из ROMI.
    static = settings.data_source != "real"
    out = []
    for c in await _channels(session):
        row = _row(c.name, c.spend, c.leads, c.deals, c.payments, c.revenue, c.margin,
                   static=static)
        row["color"] = c.color
        row["campaigns"] = [
            _row(k.name, k.spend, k.leads, k.deals, k.payments, k.revenue, k.margin,
                 campaign=True, static=static)
            for k in c.campaigns
        ]
        out.append(row)
    return out


async def channels_table(
    session: AsyncSession,
    channel: str = "all",
    period: str = "30",
    legal_entity: str = "all",
) -> list[dict]:
    """Сводка по каналам и кампаниям за выбранный период.

    В боевом режиме пересобирается из посуточного расхода Директа и сделок за тот
    же период — иначе таблица оставалась итогом за всё окно выгрузки и не менялась
    при переключении «сегодня / 7 дней / 30 дней / квартал».
    """
    rebuilt = (
        await ch_svc.for_period(session, period, legal_entity=legal_entity)
        if settings.data_source == "real" else None
    )
    if rebuilt is None:
        rows = await _stored_table(session)
    else:
        rows = []
        for c in rebuilt:
            row = _row(c["name"], c["spend"], c["leads"], c["deals"], c["payments"],
                       c["revenue"], c["margin"], static=False)
            row["color"] = c["color"]
            row["campaigns"] = [
                _row(k["name"], k["spend"], k["leads"], k["deals"], k["payments"],
                     k["revenue"], k["margin"], campaign=True, static=False)
                for k in c["campaigns"]
            ]
            rows.append(row)

    if channel and channel != "all":
        rows = [r for r in rows if r["name"] == channel]
    return rows


async def _chart_channels(
    session: AsyncSession, period: str, legal_entity: str
) -> list[dict]:
    rebuilt = (
        await ch_svc.for_period(session, period, legal_entity=legal_entity)
        if settings.data_source == "real" else None
    )
    if rebuilt is not None:
        return rebuilt
    return [
        {
            "name": c.name, "color": c.color, "spend": c.spend,
            "margin": c.margin, "campaigns": [
                {
                    "name": k.name, "spend": k.spend, "margin": k.margin,
                    "revenue": k.revenue,
                }
                for k in c.campaigns
            ],
        }
        for c in await _channels(session)
    ]


async def romi_channels_chart(
    session: AsyncSession, period: str = "30", legal_entity: str = "all"
) -> list[dict]:
    """Данные для сравнения расхода и маржи по каналам (chart-romi2)."""
    chs = await _chart_channels(session, period, legal_entity)
    return [
        {"name": c["name"], "short_name": f.short_channel(c["name"]),
         "spend": c["spend"], "margin": c["margin"], "color": c["color"]}
        for c in chs
    ]


async def campaigns_bubble(
    session: AsyncSession, period: str = "30", legal_entity: str = "all"
) -> list[dict]:
    """Пузырьковая диаграмма эффективности кампаний (chart-bubble)."""
    chs = await _chart_channels(session, period, legal_entity)
    out = []
    for c in chs:
        for k in c["campaigns"]:
            out.append({
                "name": k["name"], "spend": k["spend"],
                "romi": f.romi_of(k["spend"], k["margin"]),
                "revenue": k["revenue"], "color": c["color"],
            })
    return out


async def minus_words(session: AsyncSession) -> dict:
    rows = (await session.execute(
        select(MinusWord).order_by(MinusWord.position)
    )).scalars().all()
    total_spend = sum(r.spend for r in rows)
    camps = len({r.camp for r in rows})
    items = [
        {
            "phrase": r.phrase, "camp": r.camp, "level": r.level, "shows": r.shows,
            "clicks": r.clicks, "spend": r.spend, "spend_display": f.money(r.spend),
            "conv": r.conv, "deals": r.deals, "reason": r.reason, "conf": r.conf,
            "status": r.status,
        }
        for r in rows
    ]
    return {
        "summary": {
            "count": len(rows), "spend": total_spend,
            "spend_display": f"≈ {f.money_short(total_spend)}", "camps": camps,
        },
        "items": items,
    }
