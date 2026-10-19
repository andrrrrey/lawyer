"""Проверки ролей, доступа и сокрытия финансов."""

from fastapi.testclient import TestClient

from app.api.dashboard import _scope_plan_rows
from app.api.deps import AuthUser, scoped_legal_entities
from app.main import app


def _ensure_structure(client: TestClient) -> tuple[dict, dict]:
    config = client.get("/api/admin/business-settings").json()
    department = next((row for row in config["departments"] if row["key"] == "role_test_dept"), None)
    if department is None:
        department = {"key": "role_test_dept", "name": "Тестовый отдел", "enabled": True}
        config["departments"].append(department)
    employee = next((row for row in config["employees"] if row["key"] == "role_test_employee"), None)
    if employee is None:
        manager_name = client.get("/api/dashboard/leads").json()[0]["mgr"]
        employee = {
            "key": "role_test_employee", "name": manager_name,
            "crm_source": config["crm_sources"][0]["key"], "bitrix_user_id": "role-test",
            "legal_entity_key": config["legal_entities"][0]["key"],
            "department_key": department["key"], "enabled": True,
        }
        config["employees"].append(employee)
    response = client.put("/api/admin/business-settings", json=config)
    assert response.status_code == 200
    return employee, department


def test_owner_can_manage_users_and_manager_is_restricted(client: TestClient) -> None:
    employee, _ = _ensure_structure(client)
    created = client.post("/api/admin/users", json={
        "login": "role-test-manager",
        "password": "safe-test-password",
        "role": "manager",
        "employee_key": employee["key"],
        "department_key": employee.get("department_key", ""),
        "enabled": True,
    })
    assert created.status_code == 201

    with TestClient(app) as manager:
        login = manager.post("/api/auth/login", json={
            "login": "role-test-manager", "password": "safe-test-password",
        })
        assert login.status_code == 200
        assert login.json()["role"] == "manager"
        assert manager.get("/api/admin/users").status_code == 403
        assert manager.get("/api/integrations").status_code == 403
        assert manager.get("/api/analytics/chain").status_code == 403
        assert manager.get("/api/dashboard/expenses-by-article").status_code == 403

        cards = manager.get("/api/dashboard/kpis").json()
        assert all(row["kind"] != "money" for row in cards)
        leads = manager.get("/api/dashboard/leads").json()
        assert all(row["mgr"] == employee["name"] for row in leads)
        assert all(row["amount_display"] == "Скрыто" for row in leads)

    client.delete(f"/api/admin/users/{created.json()['id']}")


def test_disabled_user_cannot_login(client: TestClient) -> None:
    _, department = _ensure_structure(client)
    created = client.post("/api/admin/users", json={
        "login": "role-test-disabled",
        "password": "safe-test-password",
        "role": "head",
        "employee_key": "",
        "department_key": department["key"],
        "enabled": False,
    })
    assert created.status_code == 201
    with TestClient(app) as disabled:
        response = disabled.post("/api/auth/login", json={
            "login": "role-test-disabled", "password": "safe-test-password",
        })
        assert response.status_code == 401
    client.delete(f"/api/admin/users/{created.json()['id']}")


def test_head_sees_own_department_and_company_plans() -> None:
    """Руководителю доступны план отдела и общий план его юрлица."""
    rows = [
        {"key": "dept-u", "scope_type": "department", "scope_key": "sales",
         "legal_entity_key": "urpase"},
        {"key": "dept-other", "scope_type": "department", "scope_key": "other",
         "legal_entity_key": "uo"},
        {"key": "company-u", "scope_type": "company", "scope_key": "urpase",
         "legal_entity_key": "urpase"},
        {"key": "company-c", "scope_type": "company", "scope_key": "csv",
         "legal_entity_key": "csv"},
        {"key": "company-o", "scope_type": "company", "scope_key": "uo",
         "legal_entity_key": "uo"},
    ]
    config = {"employees": [
        {"key": "e1", "department_key": "sales", "legal_entity_key": "urpase",
         "enabled": True},
        {"key": "e2", "department_key": "sales", "legal_entity_key": "csv",
         "enabled": True},
    ]}
    user = AuthUser(login="head", role="head", department_key="sales")

    visible = _scope_plan_rows(rows, user, config)

    assert [row["key"] for row in visible] == ["dept-u", "company-u", "company-c"]


def test_legal_entity_head_sees_whole_entities() -> None:
    user = AuthUser(
        login="head", role="head", scope_mode="legal_entities",
        legal_entity_keys=("urpase", "csv"),
    )
    rows = [
        {"key": "u", "legal_entity_key": "urpase"},
        {"key": "c", "legal_entity_key": "csv"},
        {"key": "o", "legal_entity_key": "uo"},
    ]

    assert scoped_legal_entities(user, []) == ["csv", "urpase"]
    assert scoped_legal_entities(user, ["urpase", "uo"]) == ["urpase"]
    assert scoped_legal_entities(user, ["uo"]) == ["__no_access__"]
    assert [row["key"] for row in _scope_plan_rows(rows, user, {})] == ["u", "c"]
