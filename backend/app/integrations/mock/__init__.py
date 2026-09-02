"""Мок-реализации адаптеров на демо-данных прототипа (app.seeds)."""

from app.integrations.mock.bitrix24 import MockBitrix24Adapter
from app.integrations.mock.calltouch import MockCalltouchAdapter
from app.integrations.mock.moysklad import MockMoyskladAdapter
from app.integrations.mock.onec import MockOneCAdapter
from app.integrations.mock.yandex_direct import MockYandexDirectAdapter
from app.integrations.mock.yandex_metrika import MockYandexMetrikaAdapter

__all__ = [
    "MockBitrix24Adapter",
    "MockCalltouchAdapter",
    "MockMoyskladAdapter",
    "MockOneCAdapter",
    "MockYandexDirectAdapter",
    "MockYandexMetrikaAdapter",
]
