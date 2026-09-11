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

VAT_RATE = 0.20


def vat_to_net(gross: float) -> float:
    """Сумма с НДС → без НДС (единая база для сопоставления с Метрикой)."""
    return gross / (1 + VAT_RATE)


def vat_to_gross(net: float) -> float:
    """Сумма без НДС → с НДС."""
    return net * (1 + VAT_RATE)


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
