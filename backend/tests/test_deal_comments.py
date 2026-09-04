"""Построчные комментарии по фактам CRM и сохранение LLM-версии до изменения фактов."""

from __future__ import annotations

import asyncio
import pathlib
import tempfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.core.db import Base
from app.models import Deal
from app.services import deal_comments

DB_PATH = pathlib.Path(tempfile.gettempdir()) / "lawyer_deal_comments_test.db"


def test_baseline_comments_fill_every_deal_and_preserve_current_llm() -> None:
    async def run() -> None:
        if DB_PATH.exists():
            DB_PATH.unlink()
        engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", poolclass=NullPool)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with maker() as session:
                session.add(Deal(
                    position=1, external_id="1", crm_source="box", entity_type="deal",
                    name="Тест", src="Сайт", mgr="Иванов", status_label="В работе",
                    status_class="st-mid", stage="Квалификация", amount=0,
                    has_open_action=True,
                ))
                await session.commit()
                result = await deal_comments.refresh_baseline(session)
                assert result == {"count": 1, "changed": 1}
                deal = (await session.execute(select(Deal))).scalar_one()
                assert "Квалификация" in deal.ai_comment
                fingerprint = deal.ai_comment_fingerprint

                deal.ai_comment = "Проверить следующий контакт с клиентом."
                deal.ai_comment_source = "llm"
                await session.commit()
                await deal_comments.refresh_baseline(session)
                await session.refresh(deal)
                assert deal.ai_comment == "Проверить следующий контакт с клиентом."

                deal.stage = "Согласование"
                await session.commit()
                await deal_comments.refresh_baseline(session)
                await session.refresh(deal)
                assert deal.ai_comment_source == "baseline"
                assert deal.ai_comment_fingerprint != fingerprint
                assert "Согласование" in deal.ai_comment
        finally:
            await engine.dispose()
            if DB_PATH.exists():
                DB_PATH.unlink()

    asyncio.run(run())
