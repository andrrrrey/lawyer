"""Период отчёта: множители и подписи (PMUL / PLABEL).

Помимо пресетов (today/7/30/quarter) поддерживаются пользовательские периоды:

* ``date:YYYY-MM-DD`` — одна точная дата;
* ``range:YYYY-MM-DD:YYYY-MM-DD`` — интервал дат (границы включительно).

Пользовательские периоды разбираются здесь же, поэтому все витрины, которые уже
ходят через ``per.start`` / ``per.end`` / ``per.label``, получают их без изменений.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.seeds.kpi import PLABEL, PMUL

DEFAULT_PERIOD = "30"
REPORT_TIMEZONE = ZoneInfo("Europe/Moscow")

# Длительность периодов (дней) — реальная фильтрация по датам в боевом режиме.
PERIOD_DAYS: dict[str, int] = {"today": 1, "7": 7, "30": 30, "quarter": 90}

# Окно выгрузки источников: покрывает максимальный период дашборда (квартал)
# с запасом, чтобы переключатель периода работал для всех значений, а не только
# для 30 дней. Используется и конвейером выгрузки, и боевыми адаптерами.
WINDOW_DAYS = 95

# Пользовательский период: одна дата либо интервал дат (границы включительно).
_CUSTOM_RE = re.compile(
    r"^(?:date:(\d{4}-\d{2}-\d{2})|range:(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2}))$"
)


def _parse_custom(period: str | None) -> tuple[date, date] | None:
    """Возвращает (начальная_дата, конечная_дата) для кастомного периода либо None."""
    if not period:
        return None
    m = _CUSTOM_RE.match(period)
    if not m:
        return None
    if m.group(1):
        d = date.fromisoformat(m.group(1))
        return d, d
    a, b = date.fromisoformat(m.group(2)), date.fromisoformat(m.group(3))
    return (a, b) if a <= b else (b, a)


def is_custom(period: str | None) -> bool:
    return _parse_custom(period) is not None


def norm_period(period: str | None) -> str:
    if period in PMUL or is_custom(period):
        return period  # type: ignore[return-value]
    return DEFAULT_PERIOD


def mult(period: str | None) -> float:
    custom = _parse_custom(period)
    if custom is not None:
        # В демо-режиме кастомный период масштабирует 30-дневный базлайн
        # пропорционально числу дней (в боевом режиме множитель не применяется).
        return _inclusive_days(custom) / PERIOD_DAYS["30"]
    return PMUL[norm_period(period)]


def label(period: str | None) -> str:
    custom = _parse_custom(period)
    if custom is not None:
        a, b = custom
        if a == b:
            return f"за {a.strftime('%d.%m.%Y')}"
        return f"за {a.strftime('%d.%m')}–{b.strftime('%d.%m.%Y')}"
    return PLABEL[norm_period(period)]


def _inclusive_days(custom: tuple[date, date]) -> int:
    a, b = custom
    return (b - a).days + 1


def days(period: str | None) -> int:
    """Длительность периода в днях (для фильтрации по датам)."""
    custom = _parse_custom(period)
    if custom is not None:
        return _inclusive_days(custom)
    return PERIOD_DAYS[norm_period(period)]


def start(period: str | None, now: datetime) -> datetime:
    """Начало периода в часовом поясе отчёта (Москва)."""
    local_now = now.astimezone(REPORT_TIMEZONE)
    custom = _parse_custom(period)
    if custom is not None:
        return datetime.combine(custom[0], time.min, tzinfo=REPORT_TIMEZONE)
    p = norm_period(period)
    if p == "today":
        return local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_now - timedelta(days=PERIOD_DAYS[p])


def end(period: str | None, now: datetime) -> datetime | None:
    """Верхняя граница периода (исключающая) или None для открытых пресетов.

    Пресеты — скользящее окно до «сейчас», поэтому верхней границы у них нет.
    Кастомный период ограничен сверху: конечная дата включительно, то есть
    полночь следующего за ней дня (сравнение идёт как ``created_at < end``).
    """
    custom = _parse_custom(period)
    if custom is not None:
        upper = custom[1] + timedelta(days=1)
        return datetime.combine(upper, time.min, tzinfo=REPORT_TIMEZONE)
    return None
