"""Боевой адаптер HTTP-сервиса 1С:УНФ с Basic Authentication."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import settings
from app.integrations.real._http import DEFAULT_TIMEOUT, request


def _first(raw: dict, *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return default


def _money(value: Any) -> Decimal:
    text = str(value or "0").strip().replace(" ", "").replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def _crm_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"сделка", "deal", "d"}:
        return "deal"
    if text in {"лид", "lead", "l"}:
        return "lead"
    return text


def normalize_receipt(raw: dict) -> dict:
    """Нормализует русские и технические имена полей ответа 1С."""
    return {
        "registrar_id": str(
            _first(raw, "registrar_id", "РегистраторУИД", "Регистратор", "registrarId")
        ),
        "registrar_number": str(
            _first(raw, "registrar_number", "НомерРегистратора", "Номер", "registrarNumber")
        ),
        "registrar_type": str(
            _first(raw, "registrar_type", "ТипРегистратора", "ВидДокумента", "registrarType")
        ),
        "registrar_date": _first(
            raw, "registrar_date", "ДатаРегистратора", "Дата", "registrarDate", default=None
        ),
        "organization_id": str(
            _first(raw, "organization_id", "ОрганизацияУИД", "organizationId")
        ),
        "organization_name": str(
            _first(raw, "organization_name", "Организация", "organizationName")
        ),
        "organization_inn": str(
            _first(raw, "organization_inn", "ИННОрганизации", "organizationInn")
        ),
        "counterparty_id": str(
            _first(raw, "counterparty_id", "КонтрагентУИД", "counterpartyId")
        ),
        "counterparty_name": str(
            _first(raw, "counterparty_name", "Контрагент", "counterpartyName")
        ),
        "counterparty_inn": str(
            _first(raw, "counterparty_inn", "ИННКонтрагента", "counterpartyInn")
        ),
        "contract_id": str(_first(raw, "contract_id", "ДоговорУИД", "contractId")),
        "contract_number": str(_first(raw, "contract_number", "Договор", "contractNumber")),
        "article_id": str(_first(raw, "article_id", "СтатьяДДСУИД", "articleId")),
        "article_code": str(_first(raw, "article_code", "КодСтатьиДДС", "articleCode")),
        "article_name": str(_first(raw, "article_name", "СтатьяДДС", "articleName")).strip(),
        "amount": _money(_first(raw, "amount", "Сумма", "sum")),
        "currency": str(_first(raw, "currency", "Валюта", default="RUB")),
        "crm_external_id": str(_first(raw, "Код_BTX", "code_btx", "crmExternalId")),
        "crm_entity_type": _crm_type(
            _first(raw, "Тип_BTX", "type_btx", "crmEntityType")
        ),
        "raw": raw,
    }


def parse_receipts(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next(
            (
                payload[key]
                for key in ("data", "result", "rows", "value")
                if isinstance(payload.get(key), list)
            ),
            [],
        )
    else:
        rows = []
    return [normalize_receipt(row) for row in rows if isinstance(row, dict)]


class RealOneCAdapter:
    def __init__(
        self,
        endpoint: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.endpoint = (endpoint if endpoint is not None else settings.onec_endpoint).strip()
        self.username = username if username is not None else settings.onec_username
        self.password = password if password is not None else settings.onec_password

    def fetch_receipts(
        self, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        if not self.endpoint or not self.username or not self.password:
            raise RuntimeError("Не заданы endpoint, логин или пароль 1С")
        # Не добавляем к endpoint произвольные параметры: сервис используется
        # ровно в форме из ТЗ. При необходимости периода endpoint может содержать
        # явные шаблоны {date_from}/{date_to}.
        url = self.endpoint
        if date_from:
            url = url.replace("{date_from}", date_from)
        if date_to:
            url = url.replace("{date_to}", date_to)
        with httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            auth=httpx.BasicAuth(self.username, self.password),
            follow_redirects=True,
        ) as client:
            response = request("GET", url, client=client)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("1С вернула ответ не в формате JSON") from exc
        return parse_receipts(payload)
