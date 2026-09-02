"""Боевые адаптеры источников. Подключаются на Этапе E при получении доступов.

Сейчас — заглушки с сигнатурами протоколов, поднимают NotImplementedError.
"""

from app.integrations.real.bitrix24 import RealBitrix24Adapter
from app.integrations.real.calltouch import RealCalltouchAdapter
from app.integrations.real.moysklad import (
    FallbackMoyskladAdapter,
    PgMoyskladAdapter,
    RealMoyskladAdapter,
)
from app.integrations.real.onec import RealOneCAdapter
from app.integrations.real.yandex_direct import RealYandexDirectAdapter
from app.integrations.real.yandex_metrika import RealYandexMetrikaAdapter

__all__ = [
    "FallbackMoyskladAdapter",
    "PgMoyskladAdapter",
    "RealBitrix24Adapter",
    "RealCalltouchAdapter",
    "RealMoyskladAdapter",
    "RealOneCAdapter",
    "RealYandexDirectAdapter",
    "RealYandexMetrikaAdapter",
]
