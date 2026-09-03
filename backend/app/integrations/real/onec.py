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


def _object(raw: dict, *keys: str) -> dict:
    value = _first(raw, *keys, default={})
    return value if isinstance(value, dict) else {}


def _iso_midnight(value: str | None) -> str | None:
    """Приводит дату периода к ISO-виду, который требует HTTP-сервис 1С."""
    if not value:
        return None
    text = str(value).strip()
    if "T" not in text:
        return f"{text}T00:00:00"
    return text


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
    registrar = _object(raw, "Регистратор", "registrar")
    organization = _object(raw, "Организация", "organization")
    counterparty = _object(raw, "Контрагент", "counterparty")
    contract = _object(raw, "Договор", "contract")
    article = _object(raw, "СтатьяДДС", "article")
    order = _object(raw, "Заказ", "order")
    return {
        "registrar_id": str(
            _first(
                registrar,
                "ИД",
                "УИД",
                "id",
                default=_first(raw, "registrar_id", "РегистраторУИД", "registrarId"),
            )
        ),
        "registrar_number": str(
            _first(
                registrar,
                "Номер",
                "number",
                default=_first(raw, "registrar_number", "НомерРегистратора", "registrarNumber"),
            )
        ),
        "registrar_type": str(
            _first(
                registrar,
                "Тип",
                "type",
                default=_first(
                    raw,
                    "registrar_type",
                    "ТипРегистратора",
                    "ВидДокумента",
                    "registrarType",
                ),
            )
        ),
        "registrar_date": _first(
            registrar,
            "Дата",
            "date",
            default=_first(
                raw,
                "registrar_date",
                "ДатаРегистратора",
                "Дата",
                "Период",
                "registrarDate",
                default=None,
            ),
        ),
        "organization_id": str(
            _first(
                organization,
                "ИД",
                "УИД",
                "id",
                default=_first(raw, "organization_id", "ОрганизацияУИД", "organizationId"),
            )
        ),
        "organization_name": str(
            _first(
                organization,
                "Наименование",
                "name",
                default=_first(raw, "organization_name", "organizationName"),
            )
        ),
        "organization_inn": str(
            _first(
                organization,
                "ИНН",
                "inn",
                default=_first(raw, "organization_inn", "ИННОрганизации", "organizationInn"),
            )
        ),
        "counterparty_id": str(
            _first(
                counterparty,
                "ИД",
                "УИД",
                "id",
                default=_first(raw, "counterparty_id", "КонтрагентУИД", "counterpartyId"),
            )
        ),
        "counterparty_name": str(
            _first(
                counterparty,
                "Наименование",
                "name",
                default=_first(raw, "counterparty_name", "counterpartyName"),
            )
        ),
        "counterparty_inn": str(
            _first(
                counterparty,
                "ИНН",
                "inn",
                default=_first(raw, "counterparty_inn", "ИННКонтрагента", "counterpartyInn"),
            )
        ),
        "contract_id": str(
            _first(
                contract,
                "ИД",
                "УИД",
                "id",
                default=_first(raw, "contract_id", "ДоговорУИД", "contractId"),
            )
        ),
        "contract_number": str(
            _first(
                contract,
                "Номер",
                "number",
                default=_first(raw, "contract_number", "contractNumber"),
            )
        ),
        "article_id": str(
            _first(
                article,
                "ИД",
                "УИД",
                "id",
                default=_first(raw, "article_id", "СтатьяДДСУИД", "articleId"),
            )
        ),
        "article_code": str(
            _first(
                article,
                "Код",
                "code",
                default=_first(raw, "article_code", "КодСтатьиДДС", "articleCode"),
            )
        ),
        "article_name": str(
            _first(
                article,
                "Наименование",
                "name",
                default=_first(raw, "article_name", "СтатьяДДС", "articleName"),
            )
        ).strip(),
        "amount": _money(_first(raw, "amount", "Сумма", "sum")),
        "currency": str(_first(raw, "currency", "Валюта", default="RUB")),
        "crm_external_id": str(
            _first(
                counterparty,
                "Код_BTX",
                "code_btx",
                default=_first(
                    order,
                    "Код_BTX",
                    "code_btx",
                    default=_first(raw, "Код_BTX", "code_btx", "crmExternalId"),
                ),
            )
        ),
        "crm_entity_type": _crm_type(
            _first(
                counterparty,
                "Тип_BTX",
                "type_btx",
                default=_first(
                    order,
                    "Тип_BTX",
                    "type_btx",
                    default=_first(raw, "Тип_BTX", "type_btx", "crmEntityType"),
                ),
            )
        ),
        "row_number": str(_first(raw, "НомерСтроки", "row_number", "rowNumber")),
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
        payload = {
            "ДатаНачала": _iso_midnight(date_from),
            "ДатаОкончания": _iso_midnight(date_to),
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        with httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            auth=httpx.BasicAuth(self.username, self.password),
            follow_redirects=True,
        ) as client:
            response = request("POST", self.endpoint, client=client, json=payload)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("1С вернула ответ не в формате JSON") from exc
        return parse_receipts(payload)
