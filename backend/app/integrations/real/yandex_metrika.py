"""Боевой адаптер Яндекс Метрики (Reporting API).

Выгружает визиты по датам и источникам/UTM для сквозной цепочки. Требует
OAuth-токен и права на счётчик (YANDEX_OAUTH_TOKEN, YANDEX_METRIKA_COUNTER_ID).
Данные Метрики — без НДС (единая база расходов).
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.integrations.real._http import DEFAULT_TIMEOUT, request
from app.services.period import WINDOW_DAYS

STAT_URL = "https://api-metrika.yandex.net/stat/v1/data"


def _error_detail(resp: httpx.Response) -> str:
    """Человекочитаемая причина ошибки из ответа Stat API.

    Метрика возвращает ошибку JSON-ом (`{"errors": [...], "message": "..."}` или
    `{"message": "..."}`); при отсутствии — берём краткий фрагмент тела. Так в
    статусе пересчёта видно реальную причину (нет счётчика / нет прав), а не
    молчаливые нули визитов.
    """
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        parts: list[str] = []
        for err in body.get("errors") or []:
            if isinstance(err, dict):
                text = str(err.get("message") or err.get("error_type") or "").strip()
                if text:
                    parts.append(text)
        if not parts and body.get("message"):
            parts.append(str(body["message"]).strip())
        code = body.get("code") or resp.status_code
        detail = "; ".join(p for p in parts if p)
        if detail:
            return f"{detail} (код {code})"
    snippet = (resp.text or "").strip().replace("\n", " ")[:200]
    return snippet or f"HTTP {resp.status_code}"


def parse_visits(payload: dict) -> list[dict]:
    """{data:[{dimensions:[{name},{name}], metrics:[v]}]} → визиты по дате/источнику."""
    out: list[dict] = []
    for row in payload.get("data", []):
        dims = row.get("dimensions", [])
        metrics = row.get("metrics", [])
        out.append({
            "date": dims[0].get("name") if len(dims) > 0 else None,
            "source": dims[1].get("name") if len(dims) > 1 else None,
            "visits": int(metrics[0]) if metrics else 0,
        })
    return out


class RealYandexMetrikaAdapter:
    def __init__(
        self, oauth_token: str | None = None, counter_id: str | None = None
    ) -> None:
        self.oauth_token = oauth_token
        self.counter_id = counter_id

    def fetch_visits(self) -> list[dict]:
        counter_id = (
            self.counter_id
            if self.counter_id is not None
            else settings.yandex_metrika_counter_id
        )
        oauth_token = (
            self.oauth_token
            if self.oauth_token is not None
            else settings.yandex_oauth_token
        )
        if not str(counter_id or "").strip():
            raise RuntimeError("Яндекс Метрика: не задан номер счётчика")
        params = {
            "ids": counter_id,
            "metrics": "ym:s:visits",
            "dimensions": "ym:s:date,ym:s:lastsignTrafficSource",
            # Окно шире максимального периода дашборда (квартал) — иначе при
            # переключении периода визиты остаются 30-дневным итогом.
            "date1": f"{WINDOW_DAYS}daysAgo",
            "date2": "today",
            "limit": 10000,
        }
        headers = {"Authorization": f"OAuth {oauth_token}"}
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = request("GET", STAT_URL, client=client, params=params, headers=headers)
        # 4xx (неверный счётчик, нет прав к счётчику) request() не ретраит и
        # возвращает как есть: без явной проверки Метрика молча отдавала бы
        # «0 визитов» со статусом «ok» — расхождение с интерфейсом счётчика
        # выглядело бы как ошибка витрин, а не интеграции. Пробрасываем текст
        # ошибки Яндекса наружу — он попадёт в статус пересчёта.
        if resp.status_code != 200:
            raise RuntimeError(f"Яндекс Метрика: {_error_detail(resp)}")
        return parse_visits(resp.json())
