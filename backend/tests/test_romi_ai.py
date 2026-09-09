"""Тесты методики ROMI, AI-клиента и джоб планировщика."""

from __future__ import annotations

import pytest

from app import worker
from app.ai import client as llm
from app.services import romi


def test_vat_normalization() -> None:
    assert round(romi.vat_to_net(120)) == 100
    assert round(romi.vat_to_gross(100)) == 120


def test_romi_formula() -> None:
    # Поиск: маржа 742000, расход 214000 → 247%
    assert romi.romi(742000, 214000) == 247
    # РСЯ: маржа 316000, расход 142000 → 123%
    assert romi.romi(316000, 142000) == 123


def test_romi_undefined_for_free_or_missing() -> None:
    assert romi.romi(980000, 0) is None
    assert romi.romi(260000, None) is None


def test_margin_by_brand() -> None:
    products = [
        {"brand": "AquaLux", "profit": 100.0},
        {"brand": "AquaLux", "profit": 50.0},
        {"brand": "TeploMax", "profit": 200.0},
        {"profit": 10.0},
    ]
    result = romi.margin_by_brand(products)
    assert result["AquaLux"] == 150.0
    assert result["TeploMax"] == 200.0
    assert result["—"] == 10.0


def test_llm_client_unconfigured() -> None:
    assert llm.is_configured() is False
    with pytest.raises(llm.LLMNotConfigured):
        llm.LLMClient()


def test_scheduler_jobs_registered() -> None:
    scheduler = worker.build_scheduler()
    ids = {j.id for j in scheduler.get_jobs()}
    assert {
        "reconcile_regulation", "recompute_analytics", "refresh_ai_insights"
    } <= ids
    assert "ingest_sources" not in ids
    nightly = scheduler.get_job("recompute_analytics")
    assert str(nightly.trigger) == "cron[hour='3', minute='0']"
