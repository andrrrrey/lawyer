"""Мок-адаптер Битрикс24: отдаёт сделки из демо-данных прототипа."""

from __future__ import annotations

from app.seeds.leads import ALL_DEALS


class MockBitrix24Adapter:
    def fetch_deals(
        self, created_after: str | None = None, extra_fields: dict | None = None,  # noqa: ARG002
        modified_after: str | None = None,  # noqa: ARG002
    ) -> list[dict]:
        return [dict(row) for row in ALL_DEALS]

    def fetch_deal_fields(self) -> list[dict]:
        return []

    def fetch_stage_history(
        self, deal_ids: list[str] | None = None, changed_after: str | None = None,  # noqa: ARG002
    ) -> list[dict]:
        # История этапов моделируется полем stage_entered_at сделки.
        return []

    def fetch_activities(
        self, deal_ids: list[str], modified_after: str | None = None,  # noqa: ARG002
    ) -> list[dict]:
        # Звонки и встречи в демо моделируются флагами сделки.
        return []

    def fetch_tasks(self) -> list[dict]:
        # Задачи в демо моделируются строками Task (сид по флагу has_task сделки).
        return []

    def fetch_open_action_deal_ids(self, deal_ids: list[str]) -> set[str]:  # noqa: ARG002
        # В демо открытые задачи/дела моделируются локальными строками Task,
        # поэтому отдельный признак из «портала» не нужен.
        return set()

    def fetch_users(self) -> list[dict]:
        # В mock ответственные уже заданы именами в демо-сделках.
        return []

    def fetch_funnels(self) -> list[dict]:
        return []

    def fetch_stages(self) -> list[dict]:
        # В mock стадии уже заданы читаемыми названиями в демо-сделках.
        return []

    def fetch_sources(self) -> list[dict]:
        # В mock источники уже заданы читаемыми названиями в демо-сделках.
        return []

    def fetch_contact_phones(self, contact_ids: list[str]) -> dict[str, str]:  # noqa: ARG002
        # В mock телефоны уже заданы в демо-сделках.
        return {}

    def create_task(self, payload: dict) -> dict:
        # В mock-режиме постановка задачи в Битрикс24 не выполняется (нет записи).
        return {"ok": True, "external_id": None, "mock": True}
