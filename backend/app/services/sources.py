"""Канонизация источников сделок (SOURCE_ID Битрикс24).

Справочник источников на портале произвольный, и в выгрузку попадают как
человекочитаемые названия («Звонок», «Веб-сайт»), так и сырые коды, которые
портал не разрешил в название («call», «mail», «cpc»). В списках фильтра и на
диаграмме источников это выглядит как разные источники, хотя по смыслу «call» —
те же звонки, а «mail» — та же почта.

Здесь сырые коды сворачиваются в понятные названия и объединяются с основными
источниками. Канонизация применяется при выгрузке (`ingest._deal_from_bitrix`) и
разово доводит уже сохранённые строки (`normalize_existing`).
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Deal

# Сырой код источника (в нижнем регистре, без пробелов) → каноничное название.
# Ключи — типовые SOURCE_ID Битрикс24 и частые UTM-коды (cpc/ppc и т.п.).
_ALIASES: dict[str, str] = {
    # Звонки
    "call": "Звонок",
    "callback": "Звонок",
    "phone": "Звонок",
    "tel": "Звонок",
    # Почта
    "mail": "Электронная почта",
    "email": "Электронная почта",
    "e-mail": "Электронная почта",
    # Сайт / веб-формы
    "web": "Веб-сайт",
    "website": "Веб-сайт",
    "site": "Веб-сайт",
    "webform": "Веб-сайт",
    "crmform": "Веб-сайт",
    "form": "Веб-сайт",
    # Платная реклама
    "cpc": "Реклама",
    "cpm": "Реклама",
    "ppc": "Реклама",
    "ads": "Реклама",
    "adv": "Реклама",
    "advertising": "Реклама",
    "context": "Реклама",
    # Магазин
    "store": "Интернет-магазин",
    "shop": "Интернет-магазин",
    # Рекомендации / партнёры
    "partner": "Рекомендации",
    "recommendation": "Рекомендации",
    "referral": "Рекомендации",
    # Прочее
    "other": "Другое",
    "rc_generator": "Другое",
}

_DELETED_SOURCE_PREFIX = "Удалённый источник #"


def canonical_source(raw: str | None) -> str:
    """Каноничное название источника по сырому значению.

    Известные коды сворачиваются в понятное название; всё остальное (уже читаемые
    названия, произвольные источники портала) возвращается как есть, без пустого
    «—» вместо реального значения."""
    if raw is None:
        return "—"
    value = raw.strip()
    if not value:
        return "—"
    # Числовой SOURCE_ID без записи в актуальном справочнике Bitrix24 — это
    # исторический источник, который на портале уже удалён. Не показываем
    # пользователю голый технический код, но сохраняем его в подписи, чтобы
    # источник можно было однозначно сопоставить вручную.
    if value.isdigit():
        return f"{_DELETED_SOURCE_PREFIX}{value}"
    return _ALIASES.get(value.lower(), value)


async def normalize_existing(session: AsyncSession) -> int:
    """Однократно приводит `deals.src` уже сохранённых строк к каноничному виду.

    Возвращает число обновлённых строк. Идемпотентно: повторный вызов ничего не
    меняет. Вызывается в конце сверки сделок и доступно как команда
    `python -m app.services.sources`."""
    codes = (await session.execute(
        select(Deal.src, func.count())
        .where(Deal.src.is_not(None))
        .group_by(Deal.src)
    )).all()

    changed = 0
    for raw, n in codes:
        canon = canonical_source(raw)
        if canon != raw:
            await session.execute(
                update(Deal).where(Deal.src == raw).values(src=canon)
            )
            changed += n
    if changed:
        await session.commit()
    return changed


async def _main() -> None:
    from app.core.db import SessionLocal

    async with SessionLocal() as session:
        changed = await normalize_existing(session)
    print(f"Источники приведены к каноничному виду: обновлено строк {changed}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
