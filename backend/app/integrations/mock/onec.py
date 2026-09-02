"""Пустой mock 1С: демо-платежи пока остаются в штатных сидах."""


class MockOneCAdapter:
    def fetch_receipts(
        self, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        return []
