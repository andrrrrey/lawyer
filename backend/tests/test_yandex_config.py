"""Новая модель нескольких OAuth-доступов и ресурсов Яндекса."""

from __future__ import annotations

import httpx

from app.services import integrations_check as checks
from app.services import integrations_config as config


def test_yandex_config_preserves_secret_and_deduplicates_resources() -> None:
    existing = {
        "client_id": "approved-app",
        "credentials": [{
            "id": "oauth-1", "name": "Основной", "login": "owner",
            "token": "real-secret-token", "enabled": True,
        }],
        "direct_accounts": [], "metrika_counters": [], "last_checks": {},
    }
    incoming = {
        **existing,
        "credentials": [{**existing["credentials"][0], "token": "••••oken"}],
        "metrika_counters": [
            {"id": "counter-1", "name": "Первый", "credential_id": "oauth-1",
             "counter_id": "123", "site": "one.test", "legal_entity_key": "uo",
             "enabled": True},
            {"id": "counter-2", "name": "Дубль", "credential_id": "oauth-1",
             "counter_id": "123", "site": "one.test", "legal_entity_key": "csv",
             "enabled": True},
        ],
    }

    result = config._normalise_yandex_config(incoming, existing=existing)

    assert result["credentials"][0]["token"] == "real-secret-token"
    assert len(result["metrika_counters"]) == 1
    assert result["metrika_counters"][0]["legal_entity_key"] == "uo"


def test_direct_error_58_explains_application_problem(monkeypatch) -> None:
    def fake_post(url, **kwargs):
        return httpx.Response(
            400,
            json={"error": {"error_code": 58, "error_detail": "Незавершенная регистрация"}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(checks.httpx, "post", fake_post)
    result = checks.check_yandex_direct_resource("token", "client-login")

    assert result["status"] == "error"
    assert "не одобрено" in result["message"]
    assert "Client ID" in result["detail"]


def test_discover_metrika_counters(monkeypatch) -> None:
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            json={"counters": [{
                "id": 91458787, "name": "УрПАСЭ", "site2": {"site": "urpase.ru"},
                "owner_login": "owner", "permission": "own",
            }]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(checks.httpx, "get", fake_get)
    result = checks.discover_yandex_metrika_counters("token")

    assert result["ok"] is True
    assert result["counters"][0]["counter_id"] == "91458787"
    assert result["counters"][0]["site"] == "urpase.ru"
