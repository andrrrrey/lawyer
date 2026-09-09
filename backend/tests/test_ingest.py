"""Тесты чистой логики конвейера: атрибуция канала, агрегация, базлайн."""

from __future__ import annotations

from app.services import ingest


def test_channel_for_campaign() -> None:
    assert ingest.channel_for_campaign("Поиск · Брендовые")[0] == "Яндекс Директ — Поиск"
    assert ingest.channel_for_campaign("РСЯ · Ретаргетинг")[0] == "Яндекс Директ — РСЯ"
    # Кампании без ключевых слов попадают в канал по умолчанию.
    assert ingest.channel_for_campaign("Неизвестная")[0] == "Яндекс Директ — прочее"


def test_deduplicate_crm_rows_keeps_first_deal_and_lead_separately() -> None:
    rows = [
        {"entity_type": "lead", "external_id": "42", "name": "new"},
        {"entity_type": "lead", "external_id": "42", "name": "old"},
        {"entity_type": "deal", "external_id": "42", "name": "deal"},
        {"entity_type": "lead", "external_id": "", "name": "without id"},
    ]

    assert ingest.deduplicate_crm_rows(rows) == [rows[0], rows[2], rows[3]]


def test_aggregate_channels_vat_net() -> None:
    costs = [
        {"campaign": "Поиск · Бренд", "spend_gross": 120000, "clicks": 100, "impressions": 4000},
        {"campaign": "Поиск · Категорийные", "spend_gross": 60000, "clicks": 50, "impressions": 2000},
        {"campaign": "РСЯ · Look-alike", "spend_gross": 120000, "clicks": 200, "impressions": 9000},
    ]
    channels = ingest.aggregate_channels(costs)
    by_name = {c["name"]: c for c in channels}
    # 120000/1.2 + 60000/1.2 = 100000 + 50000 = 150000 (без НДС)
    assert by_name["Яндекс Директ — Поиск"]["spend"] == 150000
    assert len(by_name["Яндекс Директ — Поиск"]["campaigns"]) == 2
    assert by_name["Яндекс Директ — РСЯ"]["spend"] == 100000


def test_baseline_from() -> None:
    channels = [{"revenue": 500000, "margin": 170000, "spend": 100000}]
    # Оплата определяется семантикой стадии Битрикс (S — успех), а не названием.
    deals = [
        {"stage": "Оплачено", "semantic": "S", "amount": 100000, "invoice": True, "paid": True},
        {"stage": "Новое обращение", "amount": 0, "invoice": False, "paid": False},
    ]
    base = ingest.baseline_from(channels, deals)
    assert base["leads"] == 2
    assert base["deals"] == 1
    assert base["payments"] == 1
    # Выручка — из выигранных сделок Битрикс, а не из рекламной атрибуции.
    assert base["revenue"] == 100000
