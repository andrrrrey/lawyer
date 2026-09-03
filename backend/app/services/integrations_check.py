"""Проверка доступности интеграций («тест подключения»).

Каждая функция делает лёгкий реальный запрос к API провайдера с коротким
таймаутом и возвращает унифицированный результат:

    {"status": "ok" | "error" | "not_configured", "message": "...", "detail": "..."}

Проверки синхронные (httpx.Client, как в боевых адаптерах) — вызывать из
async-эндпоинта через run_in_threadpool. Значения кредов берутся из
app.core.config.settings (туда UI-настройки уже накатаны).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("lawyer.integrations")

# Короткие таймауты: тест подключения не должен «висеть».
_TIMEOUT = httpx.Timeout(12.0, connect=6.0)
# Некоторые API отвечают редиректом (напр. Calltouch) — по умолчанию httpx их не
# следует, поэтому включаем следование во всех проверках.
_FOLLOW = True


def _ok(message: str, detail: str = "") -> dict:
    return {"status": "ok", "message": message, "detail": detail}


def _err(message: str, detail: str = "") -> dict:
    return {"status": "error", "message": message, "detail": detail}


def _missing(message: str) -> dict:
    return {"status": "not_configured", "message": message, "detail": ""}


def _metrika_totals_visits(resp: httpx.Response) -> int | None:
    """Итог визитов из ответа Stat API (`{"totals": [N], ...}`) либо None."""
    try:
        totals = resp.json().get("totals") or []
    except (ValueError, AttributeError):
        return None
    if not totals:
        return None
    try:
        return int(round(float(totals[0])))
    except (TypeError, ValueError):
        return None


def _describe_exc(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "Превышено время ожидания ответа."
    if isinstance(exc, httpx.ConnectError):
        return "Не удалось установить соединение (проверьте адрес и сеть)."
    if isinstance(exc, httpx.TransportError):
        return "Сетевая ошибка при обращении к API."
    return str(exc) or exc.__class__.__name__


def check_bitrix24() -> dict:
    url = (settings.bitrix24_webhook_url or "").rstrip("/")
    if not url:
        return _missing("Не указан URL входящего вебхука.")
    try:
        resp = httpx.post(
            f"{url}/profile.json", json={}, timeout=_TIMEOUT, follow_redirects=_FOLLOW,
        )
    except Exception as exc:  # noqa: BLE001 — любой сбой = ошибка проверки
        return _err("Ошибка соединения с Битрикс24.", _describe_exc(exc))
    if resp.status_code == 401:
        return _err("Вебхук недействителен или отозван (401).")
    try:
        data = resp.json()
    except ValueError:
        return _err(f"Неожиданный ответ портала (HTTP {resp.status_code}).")
    if isinstance(data, dict) and data.get("error"):
        detail = str(data.get("error_description") or data.get("error"))
        return _err("Портал вернул ошибку.", detail)
    if resp.status_code == 200 and isinstance(data, dict) and "result" in data:
        res = data.get("result") or {}
        who = res.get("NAME") or res.get("LAST_NAME") or res.get("ID")
        return _ok("Вебхук активен.", f"Аккаунт: {who}" if who else "")
    return _err(f"Портал недоступен (HTTP {resp.status_code}).")


def _check_bitrix_connection(url: str) -> dict:
    """Проверка одного из двух подключений без подмены глобального settings."""
    base = (url or "").rstrip("/")
    if not base:
        return _missing("Не указан URL входящего вебхука.")
    try:
        resp = httpx.post(
            f"{base}/profile.json", json={}, timeout=_TIMEOUT, follow_redirects=_FOLLOW
        )
    except Exception as exc:  # noqa: BLE001
        return _err("Ошибка соединения с Bitrix24.", _describe_exc(exc))
    try:
        data = resp.json()
    except ValueError:
        return _err(f"Bitrix24 вернул не JSON (HTTP {resp.status_code}).")
    if resp.status_code == 200 and isinstance(data, dict) and not data.get("error"):
        return _ok("Доступ Bitrix24 подтверждён.")
    if resp.status_code in (401, 403):
        return _err("Вебхук Bitrix24 недействителен или не имеет прав.")
    return _err(f"Bitrix24 вернул HTTP {resp.status_code}.")


def _check_yandex_account(token: str, counter_id: str) -> dict:
    """Проверка связки Директ + Метрика одного юридического лица."""
    if not token or not counter_id:
        return _missing("Не указан OAuth-токен или номер счётчика Метрики.")
    try:
        resp = httpx.get(
            "https://api-metrika.yandex.net/stat/v1/data",
            headers={"Authorization": f"OAuth {token}"},
            params={
                "ids": counter_id,
                "metrics": "ym:s:visits",
                "date1": "yesterday",
                "date2": "yesterday",
            },
            timeout=_TIMEOUT,
            follow_redirects=_FOLLOW,
        )
    except Exception as exc:  # noqa: BLE001
        return _err("Ошибка соединения с API Яндекса.", _describe_exc(exc))
    if resp.status_code == 200:
        return _ok("Доступ к аккаунту Яндекса подтверждён.", f"Счётчик {counter_id}")
    if resp.status_code in (401, 403):
        return _err("OAuth-токен недействителен или нет доступа к счётчику.")
    return _err(f"API Яндекса вернул HTTP {resp.status_code}.")


def check_yandex_direct() -> dict:
    token = settings.yandex_oauth_token or ""
    if not token:
        return _missing("Не указан OAuth-токен Яндекса.")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
    }
    if settings.yandex_direct_login:
        headers["Client-Login"] = settings.yandex_direct_login
    body = {
        "method": "get",
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["Id", "Name"],
            "Page": {"Limit": 1},
        },
    }
    try:
        resp = httpx.post(
            "https://api.direct.yandex.com/json/v5/campaigns",
            headers=headers, json=body, timeout=_TIMEOUT, follow_redirects=_FOLLOW,
        )
    except Exception as exc:  # noqa: BLE001
        return _err("Ошибка соединения с API Директа.", _describe_exc(exc))
    try:
        data = resp.json()
    except ValueError:
        return _err(f"Неожиданный ответ API Директа (HTTP {resp.status_code}).")
    if "error" in data:
        err = data["error"]
        code = err.get("error_code")
        detail = err.get("error_detail") or err.get("error_string") or ""
        if code in (53, 58):  # невалидный/просроченный токен, нет прав
            return _err("Токен недействителен или нет доступа к API.", detail)
        return _err("API Директа вернул ошибку.", f"код {code}: {detail}")
    if resp.status_code == 200:
        campaigns = (data.get("result") or {}).get("Campaigns", [])
        return _ok("Токен принят API Директа.", f"Доступно кампаний: {len(campaigns)}+")
    return _err(f"API Директа недоступен (HTTP {resp.status_code}).")


def _fmt_int(n: int) -> str:
    """Целое с неразрывными пробелами между разрядами (как в интерфейсе Метрики)."""
    return f"{n:,}".replace(",", " ")


def check_yandex_metrika() -> dict:
    token = settings.yandex_oauth_token or ""
    counter = settings.yandex_metrika_counter_id or ""
    if not token:
        return _missing("Не указан OAuth-токен Яндекса.")
    if not counter:
        return _missing("Не указан номер счётчика Метрики.")
    # Сверка: тянем визиты именно за вчера (полный завершённый день) — это же
    # число видно в интерфейсе счётчика («Вчера»), поэтому сильное расхождение
    # сразу выдаёт, что подключён не тот счётчик, а не баг витрин.
    params = {
        "ids": counter,
        "metrics": "ym:s:visits",
        "date1": "yesterday",
        "date2": "yesterday",
        "limit": 1,
    }
    headers = {"Authorization": f"OAuth {token}"}
    try:
        resp = httpx.get(
            "https://api-metrika.yandex.net/stat/v1/data",
            params=params, headers=headers, timeout=_TIMEOUT, follow_redirects=_FOLLOW,
        )
    except Exception as exc:  # noqa: BLE001
        return _err("Ошибка соединения с API Метрики.", _describe_exc(exc))
    if resp.status_code == 200:
        visits = _metrika_totals_visits(resp)
        if visits is not None:
            return _ok(
                f"Счётчик {counter} · визитов вчера: {_fmt_int(visits)}",
                "Сверьте это число с интерфейсом Метрики за «Вчера». Сильное "
                "расхождение обычно значит, что подключён не тот счётчик.",
            )
        return _ok("Доступ к счётчику подтверждён.", f"Счётчик {counter}")
    if resp.status_code in (401, 403):
        return _err(
            "Нет доступа к счётчику.",
            "Частые причины: (1) OAuth-токен выдан только для Директа — у Метрики "
            "отдельный доступ, нужен токен с правом «Метрика: получение статистики»; "
            "(2) счётчик принадлежит другому аккаунту Яндекса, либо у владельца токена "
            "нет прав «Просмотр» на счётчик; (3) неверный номер счётчика.",
        )
    detail = ""
    try:
        detail = str(resp.json().get("message", ""))
    except ValueError:
        pass
    return _err(f"API Метрики вернул HTTP {resp.status_code}.", detail)


def check_calltouch() -> dict:
    cid = settings.calltouch_client_api_id or ""
    site = settings.calltouch_site_id or ""
    if not cid:
        return _missing("Не указан API-токен Calltouch (clientApiId).")
    if not site:
        return _missing("Не указан ID проекта Calltouch (siteId).")
    date_to = datetime.now(UTC).date()
    date_from = date_to - timedelta(days=1)
    params = {
        "clientApiId": cid,
        "dateFrom": date_from.strftime("%d/%m/%Y"),
        "dateTo": date_to.strftime("%d/%m/%Y"),
        "page": 1,
        "limit": 1,
    }
    try:
        resp = httpx.get(
            f"https://api.calltouch.ru/calls-service/RestAPI/{site}/calls-diary/calls",
            params=params, timeout=_TIMEOUT, follow_redirects=_FOLLOW,
        )
    except Exception as exc:  # noqa: BLE001
        return _err("Ошибка соединения с API Calltouch.", _describe_exc(exc))
    if resp.status_code in (401, 403):
        return _err("Нет доступа: проверьте clientApiId и права на API.")
    ctype = resp.headers.get("content-type", "")
    if resp.status_code == 200 and "json" in ctype:
        return _ok("Доступ Calltouch подтверждён.", f"Проект {site}")
    if resp.status_code == 200:
        # Редирект привёл на HTML — обычно неверный siteId (или тип доступа).
        return _err(
            "Не удалось подтвердить доступ Calltouch.",
            "API вернул не-JSON — проверьте siteId (ID проекта) и clientApiId.",
        )
    return _err(f"API Calltouch вернул HTTP {resp.status_code}.")


def _check_moysklad_db(dsn: str) -> dict:
    """Проверка доступности Postgres-реплики МойСклад (`mpdb`)."""
    from app.integrations.real import _pg
    try:
        _pg.ping(dsn)
    except Exception as exc:  # noqa: BLE001
        return _err("Реплика МойСклад (mpdb) недоступна.", _describe_exc(exc))
    return _ok("Реплика МойСклад (mpdb) отвечает.")


def check_moysklad() -> dict:
    dsn = (settings.moysklad_pg_dsn or "").strip()
    token = settings.moysklad_token or ""
    if not dsn and not token:
        return _missing("Не указаны ни DSN реплики (mpdb), ни токен МойСклад.")

    # Если задан DSN — реплика первична; сообщаем её статус, а API помечаем резервом.
    if dsn:
        db = _check_moysklad_db(dsn)
        reserve = " Резерв (API): токен задан." if token else " Резерв (API) не настроен."
        if db["status"] == "ok":
            return _ok(db["message"], (db.get("detail", "") + reserve).strip())
        # Реплика недоступна — но если есть токен, источник всё равно рабочий (через API).
        if token:
            return _err(
                "Реплика недоступна — данные пойдут из API (резерв).",
                db.get("detail", ""),
            )
        return db

    headers = {"Authorization": f"Bearer {token}", "Accept-Encoding": "gzip"}
    try:
        resp = httpx.get(
            "https://api.moysklad.ru/api/remap/1.2/context/employee",
            headers=headers, timeout=_TIMEOUT, follow_redirects=_FOLLOW,
        )
    except Exception as exc:  # noqa: BLE001
        return _err("Ошибка соединения с API МойСклад.", _describe_exc(exc))
    if resp.status_code == 200:
        try:
            emp = resp.json()
            name = emp.get("name") or emp.get("fullName") or ""
        except ValueError:
            name = ""
        return _ok("Токен МойСклад активен.", f"Сотрудник: {name}" if name else "")
    if resp.status_code in (401, 403):
        return _err("Токен недействителен или нет прав.")
    return _err(f"API МойСклад вернул HTTP {resp.status_code}.")


def check_onec() -> dict:
    endpoint = (settings.onec_endpoint or "").strip()
    username = settings.onec_username or ""
    password = settings.onec_password or ""
    if not endpoint or not username or not password:
        return _missing("Не указаны endpoint, логин или пароль 1С.")
    now = datetime.now()
    date_to = now.strftime("%Y-%m-%dT00:00:00")
    date_from = (now - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
    try:
        response = httpx.post(
            endpoint,
            auth=httpx.BasicAuth(username, password),
            json={"ДатаНачала": date_from, "ДатаОкончания": date_to},
            timeout=_TIMEOUT,
            follow_redirects=_FOLLOW,
        )
    except Exception as exc:  # noqa: BLE001
        return _err("Ошибка соединения с HTTP-сервисом 1С.", _describe_exc(exc))
    if response.status_code == 200:
        try:
            response.json()
        except ValueError:
            return _err("1С отвечает, но вернула не JSON.")
        return _ok("Доступ к 1С:УНФ подтверждён.")
    if response.status_code in (401, 403):
        return _err("1С отклонила Basic Authentication.")
    return _err(f"HTTP-сервис 1С вернул HTTP {response.status_code}.")


def check_llm() -> dict:
    base = (settings.llm_base_url or "").rstrip("/")
    key = settings.llm_api_key or ""
    if not base or not key:
        return _missing("Не указан base URL или API-ключ LLM.")
    headers = {"Authorization": f"Bearer {key}"}
    try:
        resp = httpx.get(
            f"{base}/models", headers=headers, timeout=_TIMEOUT, follow_redirects=_FOLLOW,
        )
    except Exception as exc:  # noqa: BLE001
        return _err("Ошибка соединения с LLM API.", _describe_exc(exc))
    if resp.status_code == 200:
        model = settings.llm_model or "модель по умолчанию"
        return _ok("LLM API отвечает.", f"Модель: {model}")
    if resp.status_code in (401, 403):
        return _err("API-ключ недействителен.")
    if resp.status_code == 404:
        # Эндпоинт /models может отсутствовать — соединение при этом рабочее.
        return _ok("Соединение установлено (эндпоинт /models не поддерживается).")
    return _err(f"LLM API вернул HTTP {resp.status_code}.")


_CHECKS = {
    "bitrix_box": lambda: _check_bitrix_connection(settings.bitrix_box_webhook_url),
    "bitrix_cloud": lambda: _check_bitrix_connection(settings.bitrix_cloud_webhook_url),
    "yandex_uo": lambda: _check_yandex_account(
        settings.yandex_uo_oauth_token, settings.yandex_uo_metrika_counter_id
    ),
    "yandex_csv": lambda: _check_yandex_account(
        settings.yandex_csv_oauth_token, settings.yandex_csv_metrika_counter_id
    ),
    "yandex_urpase": lambda: _check_yandex_account(
        settings.yandex_urpase_oauth_token, settings.yandex_urpase_metrika_counter_id
    ),
    "onec": check_onec,
    "llm": check_llm,
}


def run_check(provider: str) -> dict:
    """Синхронно выполняет проверку одного провайдера."""
    fn = _CHECKS.get(provider)
    if fn is None:
        return _err(f"Неизвестная интеграция: {provider}")
    checked_at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 — проверка не должна ронять запрос
        logger.warning("Проверка %s упала: %s", provider, exc)
        result = _err("Внутренняя ошибка проверки.", str(exc))
    result["provider"] = provider
    result["checked_at"] = checked_at
    return result


def run_all_checks() -> dict[str, dict]:
    return {name: run_check(name) for name in _CHECKS}
