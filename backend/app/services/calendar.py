"""Рабочее время и производственный календарь РФ.

Нормативы регламента, исчисляемые в рабочем времени (например «первый контакт —
15 минут»), считаются только внутри рабочих дней и часов, с учётом праздников.
Параметры графика берутся из настроек регламента (админ-панель).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

# Минимальный набор нерабочих дней РФ (расширяется в настройках/на Этапе E).
# Для демо-данных (август) не влияет на расчёт.
RF_HOLIDAYS_2026: set[date] = {
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6),
    date(2026, 1, 7), date(2026, 1, 8), date(2026, 2, 23), date(2026, 3, 9),
    date(2026, 5, 1), date(2026, 5, 11), date(2026, 6, 12), date(2026, 11, 4),
}


def _base_holidays(year: int) -> set[date]:
    """Ежегодные федеральные праздники; переносы добавляются в настройках."""
    return {
        *(date(year, 1, day) for day in range(1, 9)),
        date(year, 2, 23), date(year, 3, 8), date(year, 5, 1), date(year, 5, 9),
        date(year, 6, 12), date(year, 11, 4),
    }


def _parse_hm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


@dataclass
class WorkSchedule:
    """Рабочий график: дни недели, часы, учёт производственного календаря."""

    days_on: list[bool]  # Пн..Вс
    work_from: time
    work_to: time
    use_calendar: bool
    holidays: set[date]

    @classmethod
    def from_config(cls, schedule: dict | None) -> WorkSchedule:
        schedule = schedule or {}
        days_on = schedule.get("days_on") or [True, True, True, True, True, False, False]
        configured: set[date] = set()
        for value in schedule.get("holidays", []):
            try:
                configured.add(date.fromisoformat(str(value)))
            except ValueError:
                continue
        years = range(date.today().year - 2, date.today().year + 4)
        return cls(
            days_on=list(days_on),
            work_from=_parse_hm(schedule.get("work_from", "09:00")),
            work_to=_parse_hm(schedule.get("work_to", "18:00")),
            use_calendar=bool(schedule.get("production_calendar", True)),
            holidays=set().union(
                *(_base_holidays(year) for year in years),
                configured,
                RF_HOLIDAYS_2026,
            ),
        )

    def is_working_day(self, day: date) -> bool:
        if not self.days_on[day.weekday()]:
            return False
        if self.use_calendar and day in self.holidays:
            return False
        return True

    def day_minutes(self) -> int:
        return (self.work_to.hour * 60 + self.work_to.minute) - (
            self.work_from.hour * 60 + self.work_from.minute
        )


def _as_msk(dt: datetime) -> datetime:
    """Приводит момент к МСК; наивные значения (например из SQLite) считаются МСК."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MSK)
    return dt.astimezone(MSK)


def business_minutes(start: datetime, end: datetime, schedule: WorkSchedule) -> int:
    """Рабочие минуты между двумя моментами (в пределах графика, без праздников)."""
    start = _as_msk(start)
    end = _as_msk(end)
    if end <= start:
        return 0

    total = 0
    day = start.date()
    while day <= end.date():
        if schedule.is_working_day(day):
            win_start = datetime.combine(day, schedule.work_from, tzinfo=MSK)
            win_end = datetime.combine(day, schedule.work_to, tzinfo=MSK)
            seg_start = max(start, win_start)
            seg_end = min(end, win_end)
            if seg_end > seg_start:
                total += int((seg_end - seg_start).total_seconds() // 60)
        day += timedelta(days=1)
    return total


def calendar_days(start: datetime, end: datetime) -> int:
    """Календарные дни между моментами (для «зависших» и «без касания»)."""
    start = _as_msk(start)
    end = _as_msk(end)
    if end <= start:
        return 0
    return (end.date() - start.date()).days


def _plural_days(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "дня"
    return "дней"


def format_business(minutes: int, schedule: WorkSchedule) -> str:
    """Человеческая подпись рабочего интервала: «47 мин», «3ч», «1д 4ч»."""
    if minutes < 60:
        return f"{minutes} мин"
    day_min = schedule.day_minutes() or 540
    days, rest = divmod(minutes, day_min)
    hours = rest // 60
    if days and hours:
        return f"{days}д {hours}ч"
    if days:
        return f"{days}д"
    return f"{hours}ч"


def format_days(days: int) -> str:
    return f"{days} {_plural_days(days)}"
