"""Боевой адаптер Яндекс Директа (Reports API v5).

Выгружает статистику по кампаниям (расход/клики/показы) и отчёт по поисковым
запросам (для минус-слов). Требует OAuth-токен (YANDEX_OAUTH_TOKEN) и одобренную
заявку на доступ к API. Расход приходит с НДС (IncludeVAT=YES) — приведение к
единой базе выполняется в конвейере (app.services.romi).
"""

from __future__ import annotations

import io
import time
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import settings
from app.integrations.real._http import DEFAULT_TIMEOUT
from app.services.period import WINDOW_DAYS

REPORTS_URL = "https://api.direct.yandex.com/json/v5/reports"

# Сколько ждать офлайн-генерацию отчёта (сек). Тяжёлые отчёты (поисковые запросы)
# ставятся в очередь и готовятся дольше, чем отчёт по кампаниям.
_REPORT_DEADLINE = 150


def _window() -> tuple[str, str]:
    """Диапазон отчёта (YYYY-MM-DD): окно, покрывающее максимальный период дашборда.

    LAST_30_DAYS не годится — при переключении периода на «квартал» данных за
    остальные 60 дней просто нет, а «сегодня»/«7 дней» нечем ограничить.
    """
    today = datetime.now(UTC).date()
    return (today - timedelta(days=WINDOW_DAYS)).isoformat(), today.isoformat()


def parse_tsv(text: str, fields: list[str]) -> list[dict]:
    """Разбирает TSV-отчёт Reports API.

    Ответ может начинаться со строки названия отчёта (если не задан skipReportHeader),
    поэтому ищем строку заголовков — первую, где встречается хотя бы одно запрошенное
    поле, — и только затем читаем данные. Пустой отчёт (нет статистики) → [].
    """
    reader = io.StringIO(text)
    idx: dict[str, int] = {}
    for line in reader:  # пропускаем возможную строку названия отчёта
        cells = line.rstrip("\n").split("\t")
        idx = {name: cells.index(name) for name in fields if name in cells}
        if idx:
            break
    if not idx:
        return []
    rows: list[dict] = []
    for line in reader:
        line = line.rstrip("\n")
        if not line:
            continue
        cols = line.split("\t")
        rows.append({name: cols[i] for name, i in idx.items() if i < len(cols)})
    return rows


def _error_detail(resp: httpx.Response) -> str:
    """Извлекает человекочитаемый текст ошибки из ответа Reports API.

    Директ возвращает ошибку в JSON `{"error": {...}}`; при отсутствии — берём
    краткий фрагмент тела. Так в статусе пересчёта видно реальную причину, а не
    просто «400 Bad Request»."""
    try:
        err = resp.json().get("error", {})
        parts = [
            str(err.get("error_string") or "").strip(),
            str(err.get("error_detail") or "").strip(),
        ]
        text = " — ".join(p for p in parts if p)
        code = err.get("error_code")
        if text:
            return f"{text} (код {code})" if code else text
    except ValueError:
        pass
    snippet = (resp.text or "").strip().replace("\n", " ")[:200]
    return snippet or f"HTTP {resp.status_code}"


def _report(
    body: dict,
    fields: list[str],
    oauth_token: str | None = None,
    direct_login: str | None = None,
) -> list[dict]:
    token = oauth_token if oauth_token is not None else settings.yandex_oauth_token
    login = direct_login if direct_login is not None else settings.yandex_direct_login
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Language": "ru",
        "processingMode": "auto",
        "returnMoneyInMicros": "false",
        "skipReportHeader": "true",   # без строки названия отчёта — сразу заголовки колонок
        "skipReportSummary": "true",  # без строки «Total rows»
    }
    if login:
        headers["Client-Login"] = login

    # Тяжёлые отчёты (напр. по поисковым запросам) Яндекс формирует офлайн: возвращает
    # 201/202 с retryIn и ставит в очередь. Ждём генерацию до _REPORT_DEADLINE секунд,
    # уважая retryIn (с разумным потолком), а не фиксированные 6 попыток.
    deadline = time.monotonic() + _REPORT_DEADLINE
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        while time.monotonic() < deadline:
            resp = client.post(REPORTS_URL, headers=headers, json=body)
            if resp.status_code == 200:
                return parse_tsv(resp.text, fields)
            if resp.status_code in (201, 202):
                wait = int(resp.headers.get("retryIn", 5) or 5)
                time.sleep(max(1, min(wait, 20)))
                continue
            # Любой другой код — ошибка API: пробрасываем текст Яндекса наружу.
            raise RuntimeError(f"Яндекс Директ: {_error_detail(resp)}")
    raise RuntimeError("Отчёт Яндекс Директа не готов после нескольких попыток")


class RealYandexDirectAdapter:
    def __init__(self, oauth_token: str | None = None, direct_login: str | None = None) -> None:
        self.oauth_token = oauth_token
        self.direct_login = direct_login

    def _report(self, body: dict, fields: list[str]) -> list[dict]:
        if self.oauth_token is None and self.direct_login is None:
            return _report(body, fields)
        return _report(body, fields, self.oauth_token, self.direct_login)

    def fetch_channels(self) -> list[dict]:
        """Статистика кампаний по дням (строка = кампания × дата).

        Разбивка по дате обязательна: без неё расход и клики — один итог за 30
        дней, и переключатель периода на дашборде/в аналитике ничего не меняет.
        """
        # CampaignId — для атрибуции сделок по utm_campaign (обычно = id кампании).
        fields = ["Date", "CampaignId", "CampaignName", "Cost", "Clicks", "Impressions"]
        date_from, date_to = _window()
        body = {"params": {
            "SelectionCriteria": {"DateFrom": date_from, "DateTo": date_to},
            "FieldNames": fields,
            "ReportName": f"campaigns_{int(time.time())}",
            "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
            "DateRangeType": "CUSTOM_DATE",
            "Format": "TSV",
            "IncludeVAT": "YES",
            "IncludeDiscount": "NO",
        }}
        rows = self._report(body, fields)
        return [{
            "date": r.get("Date") or None,
            "campaign_id": r.get("CampaignId", ""),
            "campaign": r.get("CampaignName", ""),
            "spend_gross": int(float(r.get("Cost", 0) or 0)),
            "clicks": int(float(r.get("Clicks", 0) or 0)),
            "impressions": int(float(r.get("Impressions", 0) or 0)),
        } for r in rows if r.get("CampaignName")]

    def fetch_search_queries(self) -> list[dict]:
        fields = ["Query", "CampaignName", "Impressions", "Cost", "Clicks", "Conversions"]
        date_from, date_to = _window()
        body = {"params": {
            "SelectionCriteria": {"DateFrom": date_from, "DateTo": date_to},
            "FieldNames": fields,
            "ReportName": f"queries_{int(time.time())}",
            "ReportType": "SEARCH_QUERY_PERFORMANCE_REPORT",
            "DateRangeType": "CUSTOM_DATE",
            "Format": "TSV",
            "IncludeVAT": "YES",
            "IncludeDiscount": "NO",
        }}
        rows = self._report(body, fields)
        return [{
            "phrase": r.get("Query", ""),
            "camp": r.get("CampaignName", ""),
            "shows": int(float(r.get("Impressions", 0) or 0)),
            "spend": int(float(r.get("Cost", 0) or 0)),
            "clicks": int(float(r.get("Clicks", 0) or 0)),
            "conv": int(float(r.get("Conversions", 0) or 0)),
        } for r in rows if r.get("Query")]
