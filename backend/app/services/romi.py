"""Методика расчёта окупаемости маркетинга по фактической выручке 1С.

Ключевые правила методики:
- расходы Яндекс Директа приводятся к единой базе НДС (в API Директа — с НДС,
  в Метрике — без НДС); здесь база — без НДС;
- ROMI по выручке = (выручка − расход) / расход × 100; для каналов без
  подключённого источника расхода ROMI не определён;
- себестоимость услуг не поступает, поэтому маржа пользователю не показывается.

На Этапе B/D демо-данные уже приведены к единой базе; функции применяются при
подключении боевых источников (Этап E) и покрыты тестами.
"""

from __future__ import annotations

from datetime import date, datetime

VAT_RATE_BEFORE_2026 = 0.20
VAT_RATE_FROM_2026 = 0.22
VAT_RATE_CHANGE_DATE = date(2026, 1, 1)


def vat_rate(value: date | datetime | str | None = None) -> float:
    """Ставка НДС для даты расхода; без даты сохраняем прежнюю ставку 20%."""
    if isinstance(value, datetime):
        value = value.date()
    elif isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            value = None
    if value and value >= VAT_RATE_CHANGE_DATE:
        return VAT_RATE_FROM_2026
    return VAT_RATE_BEFORE_2026


def vat_to_net(gross: float, occurred_on: date | datetime | str | None = None) -> float:
    """Сумма с НДС → без НДС по ставке, действующей на дату расхода."""
    return gross / (1 + vat_rate(occurred_on))


def vat_to_gross(net: float, occurred_on: date | datetime | str | None = None) -> float:
    """Сумма без НДС → с НДС по ставке, действующей на указанную дату."""
    return net * (1 + vat_rate(occurred_on))


def romi(revenue: float, spend: float | None) -> int | None:
    """ROMI по выручке, %. None — расход не подключён или равен нулю."""
    if spend is None or spend <= 0:
        return None
    return round((revenue - spend) / spend * 100)


def margin_by_brand(products: list[dict]) -> dict[str, float]:
    """Агрегирует маржу по брендам из прибыльности товаров (МойСклад).

    Ожидает записи вида {'brand': str, 'profit': float}. Товары без бренда
    группируются под ключом «—».
    """
    result: dict[str, float] = {}
    for p in products:
        brand = p.get("brand") or "—"
        result[brand] = result.get(brand, 0.0) + float(p.get("profit", 0) or 0)
    return result
