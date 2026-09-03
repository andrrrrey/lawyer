"""Тесты разбора ответов боевых адаптеров (чистые функции, без сети)."""

from __future__ import annotations

import httpx
import pytest

from app.integrations.real import bitrix24, calltouch, moysklad, onec, yandex_direct, yandex_metrika


def test_direct_parse_tsv() -> None:
    text = "CampaignName\tCost\tClicks\tImpressions\nПоиск · Бренд\t38000\t120\t4300\n"
    rows = yandex_direct.parse_tsv(text, ["CampaignName", "Cost", "Clicks", "Impressions"])
    assert rows == [{"CampaignName": "Поиск · Бренд", "Cost": "38000", "Clicks": "120", "Impressions": "4300"}]


def test_bitrix_normalize_deal() -> None:
    raw = {"ID": 3390, "TITLE": "ООО «ТеплоДом»", "STAGE_ID": "C1:PREPARATION",
           "OPPORTUNITY": "145000", "ASSIGNED_BY_ID": "12", "SOURCE_ID": "CALL"}
    d = bitrix24.normalize_deal(raw)
    assert d["external_id"] == "3390"
    assert d["ref"] == "Сделка #3390"
    assert d["name"] == "ООО «ТеплоДом»"
    assert d["amount"] == 145000
    assert d["stage"] == "C1:PREPARATION"


def test_onec_uses_post_with_iso_period_body(monkeypatch) -> None:
    calls: list[tuple[str, str, dict]] = []

    class FakeResponse:
        @staticmethod
        def json() -> dict:
            return {"result": []}

    def fake_request(method, url, *, client, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(onec, "request", fake_request)
    adapter = onec.RealOneCAdapter(
        endpoint="http://1c.example/receipts", username="user", password="secret"
    )
    assert adapter.fetch_receipts("2026-08-01", "2026-08-31") == []
    assert calls == [(
        "POST",
        "http://1c.example/receipts",
        {"json": {
            "ДатаНачала": "2026-08-01T00:00:00",
            "ДатаОкончания": "2026-08-31T00:00:00",
        }},
    )]


def test_metrika_parse_visits() -> None:
    payload = {"data": [
        {"dimensions": [{"name": "2026-08-01"}, {"name": "Переходы из рекламы"}], "metrics": [320]},
    ]}
    visits = yandex_metrika.parse_visits(payload)
    assert visits[0] == {"date": "2026-08-01", "source": "Переходы из рекламы", "visits": 320}


def test_metrika_error_detail_extracts_api_message() -> None:
    """Ошибка счётчика/прав вытаскивается из JSON-ответа Stat API (не молчаливые нули)."""
    resp = httpx.Response(
        403,
        json={"errors": [{"error_type": "access_denied",
                          "message": "No access to counter"}], "code": 403},
        request=httpx.Request("GET", yandex_metrika.STAT_URL),
    )
    detail = yandex_metrika._error_detail(resp)
    assert "No access to counter" in detail
    assert "403" in detail


def test_metrika_fetch_visits_raises_on_non_200(monkeypatch) -> None:
    """Не-200 от Метрики поднимается как ошибка интеграции, а не парсится как «0 визитов»."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "yandex_metrika_counter_id", "12345678", raising=False)
    monkeypatch.setattr(settings, "yandex_oauth_token", "token", raising=False)

    def fake_request(*args, **kwargs):
        return httpx.Response(
            400,
            json={"message": "Wrong counter id", "code": 400},
            request=httpx.Request("GET", yandex_metrika.STAT_URL),
        )

    monkeypatch.setattr(yandex_metrika, "request", fake_request)
    with pytest.raises(RuntimeError, match="Яндекс Метрика"):
        yandex_metrika.RealYandexMetrikaAdapter().fetch_visits()


def test_metrika_fetch_visits_requires_counter(monkeypatch) -> None:
    """Пустой номер счётчика — сразу ошибка интеграции, без сетевого запроса."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "yandex_metrika_counter_id", "", raising=False)
    with pytest.raises(RuntimeError, match="счётчик"):
        yandex_metrika.RealYandexMetrikaAdapter().fetch_visits()


def test_calltouch_parse_calls() -> None:
    payload = {"records": [
        {"callDate": "2026-08-01 14:12", "source": "yandex", "duration": 192, "phoneNumber": "+79001110011"},
    ]}
    calls = calltouch.parse_calls(payload)
    assert calls[0]["source"] == "yandex"
    assert calls[0]["duration_sec"] == 192


def test_moysklad_parse_products_and_profit() -> None:
    products = moysklad.parse_products([
        {"id": "p1", "name": "Краска А", "productFolder": {"name": "AquaLux"}, "buyPrice": {"value": 50000}},
    ])
    assert products[0]["brand"] == "AquaLux"
    assert products[0]["cost_price"] == 500.0  # 50000 копеек → 500 ₽

    profit = moysklad.parse_profit([
        {"assortment": {"name": "Краска А"}, "profit": 30000, "sellCostSum": 50000},
    ])
    assert profit[0]["name"] == "Краска А"
    assert profit[0]["profit"] == 300.0


def test_bitrix_fetch_stages_and_sources_split_by_entity(monkeypatch) -> None:
    """crm.status.list отдаёт все справочники разом — их нельзя смешивать."""
    statuses = [
        {"ENTITY_ID": "DEAL_STAGE", "STATUS_ID": "NEW", "NAME": "Новое обращение"},
        {"ENTITY_ID": "DEAL_STAGE_1", "STATUS_ID": "C1:NEW", "NAME": "Новый заказ"},
        {"ENTITY_ID": "SOURCE", "STATUS_ID": "site", "NAME": "Сайт"},
        {"ENTITY_ID": "SOURCE", "STATUS_ID": "NEW", "NAME": "Звонок"},
    ]
    monkeypatch.setattr(bitrix24, "_call", lambda method, params=None: statuses)
    adapter = bitrix24.RealBitrix24Adapter()

    stages = {s["id"]: s["name"] for s in adapter.fetch_stages()}
    assert stages == {"NEW": "Новое обращение", "C1:NEW": "Новый заказ"}
    # Источник с тем же кодом не должен перекрывать название стадии.
    sources = {s["id"]: s["name"] for s in adapter.fetch_sources()}
    assert sources == {"site": "Сайт", "NEW": "Звонок"}


def _rest_stub(calls: list[tuple[str, dict]], *, deal_responsible: str = "12"):
    """Заглушка REST: сделка с ответственным, создание задачи и дела, справочник имён."""
    def fake_rest(method: str, payload: dict):
        calls.append((method, payload))
        if method == "crm.deal.get":
            return {"ID": payload["id"], "ASSIGNED_BY_ID": deal_responsible}
        if method == "tasks.task.add":
            return {"task": {"id": 555}}
        if method == "user.get":
            return [{"ID": payload["ID"], "NAME": "Михаил", "LAST_NAME": "Иванов"}]
        return {"id": 777}

    return fake_rest


def test_bitrix_create_task_assigns_deal_responsible(monkeypatch) -> None:
    """Исполнитель задачи — ответственный по сделке; задача дублируется «делом»."""
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(bitrix24, "_rest", _rest_stub(calls))

    out = bitrix24.RealBitrix24Adapter().create_task({
        "deal_ref": "Сделка #3390", "deal_external_id": "3390",
        "title": "Свяжитесь по сделке", "assignee_id": "12", "due_at": None,
    })

    assert out == {
        "ok": True, "external_id": 555, "activity_id": "777",
        "assignee_id": "12", "assignee": "Михаил Иванов", "mock": False,
    }
    assert [m for m, _ in calls] == [
        "crm.deal.get", "tasks.task.add", "crm.activity.todo.add", "user.get",
    ]
    task_fields = calls[1][1]["fields"]
    assert task_fields["RESPONSIBLE_ID"] == "12"
    # Задача привязана к сделке, дело заведено в её таймлайне на того же человека.
    assert task_fields["UF_CRM_TASK"] == ["D_3390"]
    assert calls[2][1]["ownerTypeId"] == 2
    assert calls[2][1]["ownerId"] == "3390"
    assert calls[2][1]["responsibleId"] == "12"


def test_bitrix_create_task_prefers_current_responsible(monkeypatch) -> None:
    """Сделку переназначили после выгрузки — задача уходит новому ответственному."""
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(bitrix24, "_rest", _rest_stub(calls, deal_responsible="99"))

    out = bitrix24.RealBitrix24Adapter().create_task({
        "deal_external_id": "3390", "title": "t", "assignee_id": "12", "due_at": None,
    })

    assert out["assignee_id"] == "99"  # не устаревшая «12» из последней выгрузки
    assert calls[1][1]["fields"]["RESPONSIBLE_ID"] == "99"


def test_bitrix_create_task_rejects_unassigned_deal(monkeypatch) -> None:
    """ASSIGNED_BY_ID=0 — это «не назначен»: задачу «Не распределено» не создаём."""
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(bitrix24, "_rest", _rest_stub(calls, deal_responsible="0"))
    adapter = bitrix24.RealBitrix24Adapter()

    with pytest.raises(RuntimeError, match="не назначен ответственный"):
        adapter.create_task({"deal_external_id": "3390", "title": "t", "assignee_id": "0"})
    # Ни задача, ни дело не создавались.
    assert [m for m, _ in calls] == ["crm.deal.get"]


def test_bitrix_create_task_falls_back_to_stored_responsible(monkeypatch) -> None:
    """Портал не отдал сделку — берём сохранённого ответственного, а не падаем."""
    calls: list[tuple[str, dict]] = []
    stub = _rest_stub(calls)

    def flaky(method: str, payload: dict):
        if method == "crm.deal.get":
            raise RuntimeError("портал недоступен")
        return stub(method, payload)

    monkeypatch.setattr(bitrix24, "_rest", flaky)
    out = bitrix24.RealBitrix24Adapter().create_task({
        "deal_external_id": "3390", "title": "t", "assignee_id": "12", "due_at": None,
    })
    assert out["assignee_id"] == "12"


def test_bitrix_create_task_requires_deal_id(monkeypatch) -> None:
    """Без ID сделки задачу ставить некуда — это молчаливый провал."""
    monkeypatch.setattr(bitrix24, "_rest", lambda *a, **kw: pytest.fail("не должно вызываться"))
    with pytest.raises(RuntimeError, match="идентификатор"):
        bitrix24.RealBitrix24Adapter().create_task({"assignee_id": "12", "title": "t"})


def test_bitrix_rest_raises_on_error_envelope(monkeypatch) -> None:
    """Битрикс отвечает HTTP 200 и при отказе — конверт ошибки должен ломать вызов."""
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"error": "ACCESS_DENIED", "error_description": "нет прав на задачи"}

    monkeypatch.setattr(bitrix24, "request", lambda *a, **kw: FakeResponse())
    monkeypatch.setattr(bitrix24, "_base", lambda: "https://portal.example/rest/1/x")

    with pytest.raises(RuntimeError, match="нет прав на задачи"):
        bitrix24._rest("tasks.task.add", {})
