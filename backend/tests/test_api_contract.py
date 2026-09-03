"""Контрактные тесты API Этапа B: форма ответов и ключевые значения из прототипа."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_dashboard_kpis(client: TestClient) -> None:
    resp = client.get("/api/dashboard/kpis", params={"period": "30"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 8
    for card in data:
        assert {"key", "label", "display", "kind", "spark", "period_label"} <= set(card)
    by_key = {c["key"]: c for c in data}
    assert by_key["leads"]["display"] == "342"
    assert by_key["romi"]["display"] == "+197%"
    assert by_key["romi"]["value"] is None


def test_dashboard_kpis_period_scaling(client: TestClient) -> None:
    data = client.get("/api/dashboard/kpis", params={"period": "today"}).json()
    leads = next(c for c in data if c["key"] == "leads")
    assert leads["display"] == "15"  # 342 * 0.045 = 15.39 → 15
    assert leads["period_label"] == "за сегодня"


def test_dashboard_attention(client: TestClient) -> None:
    data = client.get("/api/dashboard/attention").json()
    assert data["money_at_risk"] == 241000  # 145000 + 96000 (over-нарушения)
    assert data["risk_leads"] == 4
    assert len(data["tiles"]) == 7


def test_dashboard_funnel(client: TestClient) -> None:
    data = client.get("/api/dashboard/funnel", params={"period": "30"}).json()
    assert len(data) == 5
    assert data[0] == {"label": "Лиды", "value": 342}


def test_dashboard_sources(client: TestClient) -> None:
    data = client.get("/api/dashboard/sources").json()
    assert len(data) == 5
    assert {"name", "short_name", "color", "leads"} <= set(data[0])


def test_dashboard_revenue_series(client: TestClient) -> None:
    data = client.get("/api/dashboard/revenue-series", params={"period": "30"}).json()
    assert len(data["days"]) == 7
    assert len(data["revenue"]) == 7 and len(data["margin"]) == 7


def test_dashboard_romi_by_channel(client: TestClient) -> None:
    data = client.get("/api/dashboard/romi-by-channel").json()
    # только платные каналы со spend > 0: Поиск и РСЯ
    assert len(data) == 2
    search = next(d for d in data if d["name"] == "Яндекс Директ — Поиск")
    assert search["romi"] == 247


def test_dashboard_managers(client: TestClient) -> None:
    data = client.get("/api/dashboard/managers").json()
    assert len(data) == 4
    assert {"name", "inwork", "overdue", "notask", "zone_label"} <= set(data[0])


def test_dashboard_leads_and_filters(client: TestClient) -> None:
    all_leads = client.get("/api/dashboard/leads").json()
    assert len(all_leads) == 8
    risk_only = client.get("/api/dashboard/leads", params={"risk": "risk"}).json()
    assert len(risk_only) == 4
    by_mgr = client.get("/api/dashboard/leads", params={"mgr": "Азалия Хаметова"}).json()
    assert all(x["mgr"] == "Азалия Хаметова" for x in by_mgr)


def test_monitor_stats(client: TestClient) -> None:
    data = client.get("/api/monitor/stats").json()
    assert len(data["stats"]) == 5
    assert isinstance(data["badge"], int)


def test_monitor_violations_and_filter(client: TestClient) -> None:
    allv = client.get("/api/monitor/violations").json()
    assert len(allv) == 6
    one = client.get("/api/monitor/violations", params={"ptype": "overdue_contact"}).json()
    assert len(one) == 1 and one[0]["ptype"] == "overdue_contact"


def test_monitor_review(client: TestClient) -> None:
    data = client.get("/api/monitor/review").json()
    assert len(data) == 2


def test_analytics_chain(client: TestClient) -> None:
    data = client.get("/api/analytics/chain", params={"period": "30"}).json()
    assert len(data) == 6
    assert data[0]["conversion"] is None
    assert data[1]["conversion"] is not None


def test_analytics_channels(client: TestClient) -> None:
    data = client.get("/api/analytics/channels").json()
    assert len(data) == 5
    search = next(c for c in data if c["name"] == "Яндекс Директ — Поиск")
    assert len(search["campaigns"]) == 3
    assert search["romi"]["value"] == 247
    social = next(c for c in data if c["name"] == "Соцсети")
    assert social["romi"]["display"] == "нет данных"


def test_romi_endpoints(client: TestClient) -> None:
    assert len(client.get("/api/romi/by-channel").json()) == 5
    assert len(client.get("/api/romi/campaigns").json()) == 5
    assert len(client.get("/api/romi/budget-recs").json()) == 4
    mw = client.get("/api/romi/minus-words").json()
    assert mw["summary"]["count"] == 247
    assert len(mw["items"]) == 247


def test_ai_insights(client: TestClient) -> None:
    data = client.get("/api/ai/insights").json()
    assert len(data) == 7
    assert {"sev_label", "title", "text", "rec", "src", "conf"} <= set(data[0])


def test_admin_regulation_and_history(client: TestClient) -> None:
    reg = client.get("/api/admin/regulation").json()
    assert "thresholds" in reg and "task_rules" in reg and "req_fields" in reg
    hist = client.get("/api/admin/history").json()
    assert len(hist) == 4


def test_manual_expense_crud(client: TestClient) -> None:
    created = client.post("/api/admin/expenses", json={
        "spent_at": "2026-09-03",
        "legal_entity_key": "uo",
        "article": "Реклама в Авито",
        "amount": 12500.50,
        "include_in_romi": True,
        "channel": "Авито",
        "campaign": "Юридические услуги",
        "comment": "Ручная корректировка",
    })
    assert created.status_code == 201
    row = created.json()
    assert row["article"] == "Реклама в Авито"
    assert row["amount"] == 12500.5

    listed = client.get("/api/admin/expenses").json()
    assert any(item["id"] == row["id"] for item in listed)

    assert client.delete(f"/api/admin/expenses/{row['id']}").status_code == 200
    assert all(
        item["id"] != row["id"] for item in client.get("/api/admin/expenses").json()
    )


def test_manual_romi_expense_requires_channel(client: TestClient) -> None:
    response = client.post("/api/admin/expenses", json={
        "spent_at": "2026-09-03",
        "legal_entity_key": "uo",
        "article": "Реклама",
        "amount": 1000,
        "include_in_romi": True,
        "channel": "",
    })
    assert response.status_code == 422


def test_requires_auth() -> None:
    # Отдельный клиент без входа — защищённые эндпоинты возвращают 401.
    with TestClient(app) as anon:
        assert anon.get("/api/dashboard/kpis").status_code == 401
        assert anon.get("/api/monitor/stats").status_code == 401
