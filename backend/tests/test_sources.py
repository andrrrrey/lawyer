"""Канонизация источников сделок: сырые коды → понятные названия."""

from __future__ import annotations

import asyncio
import pathlib
import tempfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 — регистрирует таблицы
from app.core.db import Base
from app.models import Deal
from app.services import sources as src_svc

DB_PATH = pathlib.Path(tempfile.gettempdir()) / "lawyer_sources_test.db"


def test_canonical_source_folds_known_codes() -> None:
    assert src_svc.canonical_source("call") == "Звонок"
    assert src_svc.canonical_source("CALL") == "Звонок"
    assert src_svc.canonical_source(" mail ") == "Электронная почта"
    assert src_svc.canonical_source("cpc") == "Реклама"
    assert src_svc.canonical_source("web") == "Веб-сайт"


def test_canonical_source_keeps_readable_names() -> None:
    # Уже понятные названия и произвольные источники портала не трогаем.
    assert src_svc.canonical_source("Звонок") == "Звонок"
    assert src_svc.canonical_source("Билайн АТС 9684457956") == "Билайн АТС 9684457956"
    assert src_svc.canonical_source(None) == "—"
    assert src_svc.canonical_source("") == "—"


def _deal(pos: int, src: str) -> Deal:
    return Deal(
        position=pos, on_dashboard=True, ref=f"#{pos}", external_id=str(pos),
        name=f"Сделка {pos}", src=src, mgr="Иванов",
        status_label="В работе", status_class="st-mid", stage="В работе", amount=0,
    )


def test_normalize_existing_merges_codes_into_names() -> None:
    """`normalize_existing` сворачивает сохранённые коды и объединяет их с названиями."""
    async def run() -> None:
        if DB_PATH.exists():
            DB_PATH.unlink()
        engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", poolclass=NullPool)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with maker() as s:
                s.add_all([
                    _deal(1, "Звонок"), _deal(2, "call"), _deal(3, "cpc"),
                    _deal(4, "mail"), _deal(5, "Электронная почта"),
                ])
                await s.commit()

                changed = await src_svc.normalize_existing(s)
                assert changed == 3  # call, cpc, mail

                counts: dict[str, int] = {}
                for src in (await s.execute(select(Deal.src))).scalars().all():
                    counts[src] = counts.get(src, 0) + 1
                # «call» слился со «Звонок», «mail» — с почтой, «cpc» стал «Реклама».
                assert counts == {"Звонок": 2, "Электронная почта": 2, "Реклама": 1}

                # Идемпотентно: повторный проход ничего не меняет.
                assert await src_svc.normalize_existing(s) == 0
        finally:
            await engine.dispose()
            if DB_PATH.exists():
                DB_PATH.unlink()

    asyncio.run(run())
