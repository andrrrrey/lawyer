"""Боевой адаптер МойСклад (JSON API 1.2).

Выгружает номенклатуру/бренды/себестоимость и отчёт прибыльности за период.
Требует токен сотрудника с правом «Видеть себестоимость, цену закупки и прибыль
товаров» (MOYSKLAD_TOKEN) — без него поля себестоимости и прибыли отсутствуют.

Соблюдаются требования API: только групповые запросы с постраничной выгрузкой,
лимиты ≤100 запросов за 5 секунд и ≤5 параллельных, keep-alive.
"""

from __future__ import annotations

import time

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.real import _pg
from app.integrations.real._http import DEFAULT_TIMEOUT, request

logger = get_logger("lawyer.integrations")

BASE = "https://api.moysklad.ru/api/remap/1.2"
_PAGE = 1000
_PAUSE = 0.06  # ≤100 запросов / 5 c


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.moysklad_token}",
        "Accept-Encoding": "gzip",
    }


def parse_products(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        buy = (r.get("buyPrice") or {}).get("value", 0)
        out.append({
            "external_id": r.get("id"),
            "name": r.get("name", ""),
            "brand": (r.get("productFolder") or {}).get("name"),
            "cost_price": float(buy) / 100.0,  # копейки → рубли
        })
    return out


def parse_profit(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        assortment = r.get("assortment") or {}
        out.append({
            "name": assortment.get("name", ""),
            "profit": float(r.get("profit", 0)) / 100.0,
            "cost": float(r.get("sellCostSum", 0)) / 100.0,
        })
    return out


def _paged(path: str, params: dict | None = None) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=_headers()) as client:
        while True:
            q = dict(params or {})
            q.update({"limit": _PAGE, "offset": offset})
            resp = request("GET", f"{BASE}/{path}", client=client, params=q)
            data = resp.json()
            batch = data.get("rows", [])
            rows.extend(batch)
            size = data.get("meta", {}).get("size", len(rows))
            offset += _PAGE
            time.sleep(_PAUSE)
            if offset >= size or not batch:
                break
    return rows


class RealMoyskladAdapter:
    def fetch_products(self) -> list[dict]:
        return parse_products(_paged("entity/product", {"expand": "productFolder"}))

    def fetch_profit(self) -> list[dict]:
        return parse_profit(_paged("report/profit/byproduct"))


# ────────────────────────────────────────────────────────────────────────────
# Postgres-реплика МойСклад (`mpdb`)
#
# Заказчик реплицирует ключевые данные МойСклад в свою БД Postgres. По его просьбе
# первичный источник — эта БД, а API МойСклад — резерв (см. FallbackMoyskladAdapter).
# Запросы возвращают колонки с фиксированными алиасами — остальной код не меняется:
#   • номенклатура → external_id, name, brand, cost_price (руб.)
#   • прибыльность → name, profit (руб.), cost (руб.)
# Таблицы реплики (по интроспекции information_schema, 2026-08):
#   ms_products — номенклатура (id, name, path_name, buy_price_value, archived)
#   ms_demands  — отгрузки/продажи (product_id, quantity, price, sum, applicable)
#
# ДОПУЩЕНИЯ (подтвердить на реальных данных, при расхождении — поправить здесь):
#   1) Денежные поля хранятся в КОПЕЙКАХ (как в API МойСклад) → делим на 100.
#   2) «Бренд» = path_name (путь папки/группы товара). Если бренды размечены иначе
#      (атрибут) — заменить источник колонки brand.
#   3) Прибыль считается как выручка − (кол-во × закупочная цена). Это ПРИБЛИЖЕНИЕ,
#      а не FIFO-себестоимость отчёта МойСклад. Для точного совпадения с отчётом МС
#      заказчик может отдать готовую вьюху прибыльности — тогда _SQL_PROFIT сведётся
#      к «SELECT name, profit, cost FROM <вьюха>».
# Если запрос падает (нет таблицы/прав) — адаптер бросает исключение, и
# FallbackMoyskladAdapter уходит в API МойСклад. Это безопасно by design.
# ────────────────────────────────────────────────────────────────────────────

_SQL_PRODUCTS = """
    SELECT
        id                                    AS external_id,
        name                                  AS name,
        NULLIF(path_name, '')                 AS brand,
        COALESCE(buy_price_value, 0) / 100.0  AS cost_price
    FROM ms_products
    WHERE archived IS NOT TRUE
"""

# Прибыль по товарам из отгрузок: выручка (кол-во×цена позиции) минус закупочная
# стоимость (кол-во×buy_price_value). Только проведённые отгрузки (applicable).
_SQL_PROFIT = """
    SELECT
        p.name AS name,
        (SUM(d.quantity * d.price)
            - SUM(d.quantity * COALESCE(p.buy_price_value, 0))) / 100.0 AS profit,
        SUM(d.quantity * COALESCE(p.buy_price_value, 0)) / 100.0        AS cost
    FROM ms_demands d
    JOIN ms_products p ON p.id = d.product_id
    WHERE d.applicable IS TRUE
    GROUP BY p.name
"""


class PgMoyskladAdapter:
    """Читает номенклатуру и прибыльность из Postgres-реплики `mpdb`.

    DSN берётся из settings.moysklad_pg_dsn (задаётся на странице «Интеграции»).
    Пустой DSN → RuntimeError, чтобы сработал резерв (API МойСклад).
    """

    def _dsn(self) -> str:
        dsn = (settings.moysklad_pg_dsn or "").strip()
        if not dsn:
            raise RuntimeError("DSN реплики МойСклад (mpdb) не задан")
        return dsn

    def fetch_products(self) -> list[dict]:
        rows = _pg.run_query(self._dsn(), _SQL_PRODUCTS)
        # Приводим себестоимость к float — в БД может быть numeric/Decimal.
        for r in rows:
            r["cost_price"] = float(r.get("cost_price") or 0)
        return rows

    def fetch_profit(self) -> list[dict]:
        rows = _pg.run_query(self._dsn(), _SQL_PROFIT)
        for r in rows:
            r["profit"] = float(r.get("profit") or 0)
            r["cost"] = float(r.get("cost") or 0)
        return rows


class FallbackMoyskladAdapter:
    """Первично — реплика `mpdb`, при недоступности/пустоте — API МойСклад.

    Реализует поведение, о котором просил заказчик: «первостепенно данные из БД,
    если их там нет — идём в API». Ошибка подключения к БД или пустой результат
    прозрачно переключают на API — пересчёт не падает.
    """

    def __init__(
        self, primary: PgMoyskladAdapter | None = None,
        secondary: RealMoyskladAdapter | None = None,
    ) -> None:
        self.primary = primary or PgMoyskladAdapter()
        self.secondary = secondary or RealMoyskladAdapter()

    def _with_fallback(self, method: str) -> list[dict]:
        # Резерв (API) доступен только при заданном токене. Если его нет — не идём в
        # API (иначе получим бесполезное «Illegal header value b'Bearer '»), а
        # показываем реальную причину сбоя реплики.
        has_api = bool((settings.moysklad_token or "").strip())
        try:
            rows = getattr(self.primary, method)()
        except Exception as exc:  # noqa: BLE001 — проблема с БД
            if has_api:
                logger.warning("МойСклад-реплика недоступна (%s): %s → резерв (API)", method, exc)
                return getattr(self.secondary, method)()
            logger.warning("МойСклад-реплика недоступна (%s): %s (резерв API не настроен)",
                           method, exc)
            raise  # без резерва — пробрасываем настоящую ошибку реплики наружу
        if rows:
            return rows
        # Реплика ответила пусто.
        if has_api:
            logger.info("МойСклад-реплика: %s вернул 0 строк → резерв (API)", method)
            return getattr(self.secondary, method)()
        return rows  # пусто и резерва нет — это не ошибка

    def fetch_products(self) -> list[dict]:
        return self._with_fallback("fetch_products")

    def fetch_profit(self) -> list[dict]:
        return self._with_fallback("fetch_profit")
