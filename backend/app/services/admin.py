"""Запись настроек регламента и откат изменений (админ-панель).

При сохранении вычисляется разница с текущей конфигурацией и по каждому
изменённому параметру создаётся запись истории (со структурными данными для
программного отката). Параметры, помеченные `crit`, влияют на расчёт нарушений.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RegulationConfig, SettingsHistory
from app.services.clock import reference_now

# Известные скалярные параметры: путь → (метка, критичность, форматтер).
_SCALAR_PARAMS: list[tuple[list, str, bool]] = [
    (["dup_rule", "value"], "Правило определения дублей", True),
    (["evaluative", "stuck_days"], "Порог «зависшей» сделки", True),
    (["evaluative", "highlight_spam"], "Подсветка перевода в «Спам»", False),
    (["evaluative", "highlight_refusal"], "Подсветка отказа «для чистоты»", False),
    (["schedule", "work_from"], "Начало рабочего дня", True),
    (["schedule", "work_to"], "Конец рабочего дня", True),
    (["schedule", "production_calendar"], "Производственный календарь РФ", True),
    (["task_logic", "assignee"], "Адресат задачи", False),
    (["task_logic", "template"], "Шаблон текста задачи", False),
]

_DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def get_path(data: dict, path: list) -> Any:
    node: Any = data
    for key in path:
        if isinstance(key, int):
            if not isinstance(node, list) or key >= len(node):
                return None
            node = node[key]
        else:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
    return node


def set_path(data: dict, path: list, value: Any) -> None:
    node: Any = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def _disp(value: Any) -> str:
    if isinstance(value, bool):
        return "вкл" if value else "выкл"
    if isinstance(value, list):
        return ", ".join(str(x) for x in value)
    return str(value)


def _disp_days(days_on: list) -> str:
    return ", ".join(_DAYS[i] for i, on in enumerate(days_on) if on) or "—"


def _disp_fields(req_fields: list) -> str:
    return ", ".join(name for name, on in req_fields if on) or "—"


def validate_config(data: Any) -> None:
    """Базовая проверка структуры конфигурации регламента."""
    if not isinstance(data, dict):
        raise ValueError("Конфигурация должна быть объектом")
    for tr in data.get("thresholds", []):
        if not isinstance(tr.get("v"), int | float):
            raise ValueError(f"Порог «{tr.get('n')}» должен быть числом")
    stuck = data.get("evaluative", {}).get("stuck_days")
    if stuck is not None and (not isinstance(stuck, int) or stuck < 1):
        raise ValueError("Порог зависшей сделки должен быть целым ≥ 1")


def compute_diff(old: dict, new: dict) -> list[dict]:
    """Список изменений с данными для отката."""
    changes: list[dict] = []

    def add(path, label, ov, nv, crit, from_disp=None, to_disp=None):
        changes.append({
            "param": label, "crit": crit, "path": path,
            "value_from": from_disp if from_disp is not None else _disp(ov),
            "value_to": to_disp if to_disp is not None else _disp(nv),
            "raw_from": {"value": ov}, "raw_to": {"value": nv},
        })

    # Пороги воронки
    for i, tr in enumerate(new.get("thresholds", [])):
        ov = get_path(old, ["thresholds", i, "v"])
        nv = tr.get("v")
        if ov is not None and ov != nv:
            u = tr.get("u", "")
            add(["thresholds", i, "v"], tr.get("n", "Порог"), ov, nv, True,
                f"{ov} {u}", f"{nv} {u}")

    # Правила по задачам
    for i, rule in enumerate(new.get("task_rules", [])):
        ov = get_path(old, ["task_rules", i, "on"])
        nv = rule.get("on")
        if ov is not None and ov != nv:
            add(["task_rules", i, "on"], f"Задача на этапе «{rule.get('n')}»", ov, nv, True)

    # Скалярные параметры
    for path, label, crit in _SCALAR_PARAMS:
        ov, nv = get_path(old, path), get_path(new, path)
        if ov != nv and nv is not None:
            add(path, label, ov, nv, crit)

    # Рабочие дни
    ov, nv = get_path(old, ["schedule", "days_on"]), get_path(new, ["schedule", "days_on"])
    if ov is not None and nv is not None and ov != nv:
        add(["schedule", "days_on"], "Рабочие дни", ov, nv, True,
            _disp_days(ov), _disp_days(nv))

    # Обязательные поля
    ov, nv = get_path(old, ["req_fields"]), get_path(new, ["req_fields"])
    if ov is not None and nv is not None and ov != nv:
        add(["req_fields"], "Обязательные поля", ov, nv, False,
            _disp_fields(ov), _disp_fields(nv))

    return changes


def _now_label() -> str:
    return reference_now().strftime("%d.%m · %H:%M")


async def _min_position(session: AsyncSession) -> int:
    rows = (await session.execute(select(SettingsHistory.position))).scalars().all()
    return min(rows) if rows else 0


async def update_regulation(session: AsyncSession, new_data: dict, user: str) -> dict:
    """Сохраняет новую конфигурацию, фиксируя изменения в истории."""
    validate_config(new_data)
    cfg = await session.get(RegulationConfig, 1)
    old_data = copy.deepcopy(cfg.data) if cfg else {}

    changes = compute_diff(old_data, new_data)

    if cfg is None:
        cfg = RegulationConfig(id=1, data=new_data)
        session.add(cfg)
    else:
        cfg.data = new_data

    pos = await _min_position(session)
    for ch in changes:
        pos -= 1
        session.add(SettingsHistory(
            position=pos, dt=_now_label(), user=user, param=ch["param"],
            value_from=ch["value_from"], value_to=ch["value_to"], crit=ch["crit"],
            path=ch["path"], raw_from=ch["raw_from"], raw_to=ch["raw_to"],
        ))
    await session.commit()
    return {"config": new_data, "changes": len(changes)}


async def rollback(session: AsyncSession, history_id: int, user: str) -> dict:
    """Откатывает конкретное изменение к прежнему значению."""
    entry = await session.get(SettingsHistory, history_id)
    if entry is None:
        raise ValueError("Запись истории не найдена")
    if not entry.path or entry.raw_from is None:
        raise ValueError("Эта запись не поддерживает автоматический откат")

    cfg = await session.get(RegulationConfig, 1)
    data = copy.deepcopy(cfg.data)
    set_path(data, entry.path, entry.raw_from["value"])
    cfg.data = data

    pos = await _min_position(session) - 1
    session.add(SettingsHistory(
        position=pos, dt=_now_label(), user=user,
        param=f"Откат: {entry.param}", value_from=entry.value_to, value_to=entry.value_from,
        crit=entry.crit, path=entry.path,
        raw_from=entry.raw_to, raw_to=entry.raw_from,
    ))
    await session.commit()
    return {"config": data, "restored": entry.param}
