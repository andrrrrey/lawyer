"""Рекомендуемое действие в сводке каналов не должно противоречить цифрам.

Баг: у сидовых каналов («Яндекс Директ — Поиск» и т.п.) действие бралось из
статичной таблицы ACTIONS по имени. В боевом режиме имена те же, а цифры
реальные — при ROMI −100% (расход есть, выручки нет) карточка всё равно
показывала «Масштабировать». Действие в боевом режиме считается из ROMI.
"""

from __future__ import annotations

from app.services import format as f


def test_seed_named_channel_uses_real_romi_when_not_static() -> None:
    # «Яндекс Директ — Поиск» есть в ACTIONS со статичной подписью «Масштабировать»,
    # но при расходе без выручки (ROMI −100%) боевой режим обязан звать ограничить.
    a = f.action_of("Яндекс Директ — Поиск", spend=36_769, revenue=0, static=False)
    assert a["label"] == "Ограничить"
    assert a["cls"] == "act-limit"


def test_seed_named_channel_keeps_static_label_in_demo() -> None:
    # Демо-режим (static=True) сохраняет заранее написанную подпись прототипа.
    a = f.action_of("Яндекс Директ — Поиск", spend=214_000, revenue=742_000, static=True)
    assert a["label"] == "Масштабировать"


def test_real_action_thresholds() -> None:
    # ROMI ≥ 200 → масштабировать; в пределах цели → под наблюдением; ниже → ограничить.
    assert f.action_of("Канал", 100, 350, static=False)["label"] == "Масштабировать"
    assert f.action_of("Канал", 100, 250, static=False)["label"] == "Под наблюдением"
    assert f.action_of("Канал", 100, 0, static=False)["label"] == "Ограничить"


def test_free_and_unconnected_channels_unaffected() -> None:
    # Бесплатный канал (spend=0) и без источника расхода (spend=None) — как раньше.
    assert f.action_of("Канал", 0, 100, static=False)["label"] == "—"
    assert f.action_of("Канал", None, 100, static=False)["label"] == "Данных недостаточно"
