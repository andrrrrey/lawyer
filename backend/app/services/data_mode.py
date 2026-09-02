"""Переключение источника данных: очистка демо в боевом режиме и обратно.

Демо-данные загружаются сидом в mock-режиме. При переходе на боевой режим их
нужно убрать, чтобы разделы показывали реальные данные (или «нет данных», если
источник не подключён), а не шаблонные значения прототипа. При возврате в mock —
демо восстанавливается.
"""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import (
    AdCost,
    AiInsight,
    Baseline,
    BudgetRec,
    Call,
    Campaign,
    Channel,
    Deal,
    ManagerControl,
    MinusWord,
    Payment,
    Product,
    SettingsHistory,
    StageHistory,
    Task,
    Violation,
    Visit,
)

logger = get_logger("lawyer.data_mode")

# Таблицы «витрин»/демо-контента, очищаемые при переходе на боевой режим
# (дети раньше родителей). Реальные данные наполняются пересчётом/генерацией.
# НЕ трогаем: KpiCard (структура карточек), RegulationConfig (настройки).
_PURGE_ORDER = [
    StageHistory, Task, Payment, Call, Campaign,
    Deal, Channel, Violation, ManagerControl, Baseline,
    AiInsight, BudgetRec, MinusWord, Product,
    # Посуточное сырьё источников: при смене режима оно устаревает вместе с
    # витринами, иначе расход/визиты «чужого» режима попадут в показатели.
    AdCost, Visit,
]

# Таблицы без реального источника выгрузки: в боевом режиме всегда пусты, пока
# не появится соответствующая интеграция/генерация. Чистятся и при пересчёте.
_NO_SOURCE_TABLES = [ManagerControl, BudgetRec, MinusWord]


async def clear_no_source_tables(session: AsyncSession) -> None:
    """Очищает демо-таблицы, у которых пока нет реального источника данных."""
    for model in _NO_SOURCE_TABLES:
        await session.execute(delete(model))
    # Демо-история регламента (без структурных данных для отката); реальные
    # записи (с path) — сохраняем.
    await session.execute(delete(SettingsHistory).where(SettingsHistory.path.is_(None)))


async def switch_to_real(session: AsyncSession) -> None:
    """Убирает демо-контент при переходе на боевой режим."""
    for model in _PURGE_ORDER:
        await session.execute(delete(model))
    await session.execute(delete(SettingsHistory).where(SettingsHistory.path.is_(None)))
    await session.commit()
    logger.info("Демо-данные очищены (переход на боевой режим)")


async def switch_to_mock(session: AsyncSession) -> None:
    """Восстанавливает демо-данные при возврате в демо-режим."""
    from app.seed import seed_all

    await seed_all(session)
    logger.info("Демо-данные восстановлены (возврат в демо-режим)")
