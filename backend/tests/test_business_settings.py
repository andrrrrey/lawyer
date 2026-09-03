"""Настройки трёх юрлиц и классификация фактов 1С."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from app.integrations.real.onec import normalize_receipt, parse_receipts
from app.seeds.business import BUSINESS_SETTINGS
from app.services.business_settings import receipt_article_operation, validate_settings
from app.services.ingest import classify_receipts


def test_defaults_contain_three_entities_and_exact_visible_articles() -> None:
    entities = {item["key"]: item for item in BUSINESS_SETTINGS["legal_entities"]}
    assert {item["name"] for item in entities.values()} == {"ЮО", "ЦСВ", "УрПАСЭ"}
    assert len(entities["uo"]["dds_articles"]) == 11
    assert len(entities["csv"]["dds_articles"]) == 8
    assert len(entities["urpase"]["dds_articles"]) == 8
    assert {key: item["inn"] for key, item in entities.items()} == {
        "uo": "6686064870",
        "csv": "6686094579",
        "urpase": "6671469916",
    }
    assert receipt_article_operation(BUSINESS_SETTINGS, "uo", "ЭРобокасса") == "income"
    # Нечёткое/регистронезависимое сопоставление намеренно запрещено.
    assert receipt_article_operation(BUSINESS_SETTINGS, "uo", "эробокасса") is None


def test_sla_keeps_source_numbering() -> None:
    rules = BUSINESS_SETTINGS["sla_profiles"][0]["rules"]
    assert [rule["source_number"] for rule in rules] == [1, 2, 3, 4, 5, 7]


def test_funnel_references_are_validated() -> None:
    data = deepcopy(BUSINESS_SETTINGS)
    data["funnels"] = [{
        "key": "bad",
        "external_id": "1",
        "crm_source": "missing",
        "legal_entity_key": "uo",
        "sla_profile_key": "default",
    }]
    with pytest.raises(ValueError, match="источник Bitrix24"):
        validate_settings(data)


def test_onec_payload_normalization_preserves_money_and_btx_fields() -> None:
    rows = parse_receipts({"result": [{
        "РегистраторУИД": "reg-1",
        "СтатьяДДС": "Юридические услуги ",
        "Сумма": "12 345,67",
        "Код_BTX": "991",
        "Тип_BTX": "deal",
    }]})
    assert rows == [normalize_receipt({
        "РегистраторУИД": "reg-1",
        "СтатьяДДС": "Юридические услуги ",
        "Сумма": "12 345,67",
        "Код_BTX": "991",
        "Тип_BTX": "deal",
    })]
    assert rows[0]["amount"] == Decimal("12345.67")
    assert rows[0]["article_name"] == "Юридические услуги"
    assert rows[0]["crm_external_id"] == "991"


def test_onec_nested_payload_from_specification_is_normalized() -> None:
    rows = parse_receipts({"result": [{
        "Период": "2026-08-18T23:59:59",
        "Регистратор": {
            "ИД": "reg-1",
            "Номер": "АБУА-000347",
            "Дата": "2026-08-18T23:59:59",
            "Тип": "ПоступлениеНаСчет",
        },
        "НомерСтроки": "1",
        "Организация": {
            "ИД": "org-1",
            "Наименование": "Юридический омбудсмен",
            "ИНН": "6686064870",
        },
        "Контрагент": {
            "ИД": "customer-1",
            "Наименование": "Клиент",
            "ИНН": "6600000000",
            "Код_BTX": "991",
            "Тип_BTX": "Сделка",
        },
        "Договор": {"ИД": "contract-1", "Номер": "2"},
        "СтатьяДДС": {
            "ИД": "article-1",
            "Код": "УА-000625",
            "Наименование": "Юридические услуги",
        },
        "Сумма": 2070,
    }]})
    assert rows[0] | {"raw": None} == {
        "registrar_id": "reg-1",
        "registrar_number": "АБУА-000347",
        "registrar_type": "ПоступлениеНаСчет",
        "registrar_date": "2026-08-18T23:59:59",
        "organization_id": "org-1",
        "organization_name": "Юридический омбудсмен",
        "organization_inn": "6686064870",
        "counterparty_id": "customer-1",
        "counterparty_name": "Клиент",
        "counterparty_inn": "6600000000",
        "contract_id": "contract-1",
        "contract_number": "2",
        "article_id": "article-1",
        "article_code": "УА-000625",
        "article_name": "Юридические услуги",
        "amount": Decimal("2070.00"),
        "currency": "RUB",
        "crm_external_id": "991",
        "crm_entity_type": "deal",
        "row_number": "1",
        "raw": None,
    }


def test_receipts_exclude_internal_transfer_and_unknown_article() -> None:
    data = deepcopy(BUSINESS_SETTINGS)
    data["legal_entities"][0]["inn"] = "1000000001"
    data["legal_entities"][1]["inn"] = "1000000002"
    rows = classify_receipts([
        {
            "registrar_type": "ПоступлениеНаСчет",
            "organization_inn": "1000000001",
            "counterparty_inn": "1000000002",
            "article_name": "Юридические услуги",
        },
        {
            "registrar_type": "ПоступлениеНаСчет",
            "organization_inn": "1000000001",
            "counterparty_inn": "5000000000",
            "article_name": "Неизвестная статья",
        },
    ], data)
    assert rows[0]["exclusion_reason"] == "internal_transfer"
    assert rows[1]["exclusion_reason"] == "unknown_dds_article"


def test_receipts_exclude_non_income_registrar_types() -> None:
    rows = classify_receipts([{
        "registrar_type": "ЧекККМВозврат",
        "organization_inn": "6686064870",
        "counterparty_inn": "6600000000",
        "article_name": "Юридические услуги",
    }], BUSINESS_SETTINGS)
    assert rows[0]["excluded"] is True
    assert rows[0]["exclusion_reason"] == "unsupported_registrar_type"


def test_business_settings_api(client) -> None:
    response = client.get("/api/admin/business-settings")
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["legal_entities"]] == [
        "ЮО", "ЦСВ", "УрПАСЭ"
    ]
