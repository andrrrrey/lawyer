"""Форматирование чисел и деривации ROMI — зеркало helper-функций прототипа
(fmt / money / moneyShort / romiOf / romiTag / actionOf)."""

from __future__ import annotations

from app.seeds.channels import ACTIONS

NBSP = " "


def fmt(n: float) -> str:
    """Целое с разделением разрядов неразрывным пробелом (ru-RU)."""
    return f"{round(n):,}".replace(",", NBSP)


def money(n: float) -> str:
    return f"{fmt(n)} ₽"


def money_short(n: float) -> str:
    a = abs(n)
    if a >= 1e6:
        return f"{n / 1e6:.2f}".replace(".", ",") + " млн ₽"
    if a >= 1e3:
        return f"{round(n / 1e3)} тыс ₽"
    return f"{fmt(n)} ₽"


def short_channel(name: str) -> str:
    return name.replace("Яндекс Директ — ", "ЯД · ")


def romi_of(spend: int | None, revenue: int) -> int | None:
    """ROMI по выручке, %. None — если расход не подключён или равен нулю."""
    if spend is not None and spend > 0:
        return round((revenue - spend) / spend * 100)
    return None


def romi_tag(spend: int | None, revenue: int) -> dict:
    """Метка ROMI: {display, cls, value}."""
    if spend is None:
        return {"display": "нет данных", "cls": "t-gray", "value": None}
    if spend == 0:
        return {"display": "бесплатный канал", "cls": "t-gray", "value": None}
    r = romi_of(spend, revenue)
    assert r is not None
    cls = "t-green" if r >= 200 else "t-amber" if r >= 80 else "t-red"
    return {"display": f"{'+' if r > 0 else ''}{r}%", "cls": cls, "value": r}


def action_of(name: str, spend: int | None, revenue: int, *, static: bool = True) -> dict:
    """Рекомендуемое действие: {label, cls, note} (перенос actionOf/ACTIONS).

    static=True — демо-режим: для сидовых каналов берётся заранее написанная
    рекомендация из ACTIONS. В боевом режиме (static=False) её брать нельзя:
    имена каналов те же, но цифры реальные, и статичная подпись
    («Масштабировать» при ROMI −100%) противоречит фактам — действие тогда
    всегда выводится из реального ROMI.
    """
    if static and name in ACTIONS:
        label, cls, note = ACTIONS[name]
    elif spend is None:
        label, cls, note = "Данных недостаточно", "act-nodata", "Источник расхода не подключён"
    elif spend == 0:
        label, cls, note = "—", "act-none", "Бесплатный канал"
    else:
        r = romi_of(spend, revenue) or 0
        if r >= 200:
            label, cls, note = "Масштабировать", "act-scale", "Высокий ROMI"
        elif r >= 120:
            label, cls, note = "Под наблюдением", "act-watch", "ROMI в пределах цели"
        elif r >= 80:
            label, cls, note = "Проверить", "act-check", "ROMI ниже цели"
        else:
            label, cls, note = "Ограничить", "act-limit", "ROMI ниже порога окупаемости"
    return {"label": label, "cls": cls, "note": note}
