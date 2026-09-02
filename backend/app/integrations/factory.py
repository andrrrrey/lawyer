"""Фабрика адаптеров: выбор mock/real по настройке DATA_SOURCE.

Единая точка выбора реализации. Замена мок→боевой сводится к переключению
DATA_SOURCE=real — сервисы и сид-загрузчик не меняются.
"""

from __future__ import annotations

from app.core.config import settings
from app.integrations import mock, real
from app.integrations.base import (
    Bitrix24Adapter,
    CalltouchAdapter,
    MoyskladAdapter,
    OneCAdapter,
    YandexDirectAdapter,
    YandexMetrikaAdapter,
)


def _is_real() -> bool:
    return settings.data_source == "real"


def get_bitrix24() -> Bitrix24Adapter:
    return real.RealBitrix24Adapter() if _is_real() else mock.MockBitrix24Adapter()


def get_bitrix24_connections() -> list[tuple[str, Bitrix24Adapter]]:
    """Два технических источника CRM; для старой установки — legacy fallback."""
    if not _is_real():
        return [("primary", mock.MockBitrix24Adapter())]
    configured = [
        ("box", settings.bitrix_box_webhook_url),
        ("cloud", settings.bitrix_cloud_webhook_url),
    ]
    result = [
        (key, real.RealBitrix24Adapter(webhook_url=url, source_key=key))
        for key, url in configured
        if (url or "").strip()
    ]
    if not result and settings.bitrix24_webhook_url:
        result.append(("primary", get_bitrix24()))
    return result


def get_bitrix24_connection(source_key: str) -> Bitrix24Adapter:
    for key, adapter in get_bitrix24_connections():
        if key == source_key:
            return adapter
    if source_key == "primary":
        return get_bitrix24()
    raise RuntimeError(f"Подключение Bitrix24 «{source_key}» не настроено")


def get_onec() -> OneCAdapter:
    return real.RealOneCAdapter() if _is_real() else mock.MockOneCAdapter()


def get_yandex_direct() -> YandexDirectAdapter:
    return real.RealYandexDirectAdapter() if _is_real() else mock.MockYandexDirectAdapter()


def get_yandex_metrika() -> YandexMetrikaAdapter:
    return real.RealYandexMetrikaAdapter() if _is_real() else mock.MockYandexMetrikaAdapter()


def get_yandex_connections() -> list[tuple[str, YandexDirectAdapter, YandexMetrikaAdapter]]:
    """По одной связке Директ + Метрика на каждое юридическое лицо."""
    if not _is_real():
        return [("", mock.MockYandexDirectAdapter(), mock.MockYandexMetrikaAdapter())]
    configured = [
        (
            "uo",
            settings.yandex_uo_oauth_token,
            settings.yandex_uo_direct_login,
            settings.yandex_uo_metrika_counter_id,
        ),
        (
            "csv",
            settings.yandex_csv_oauth_token,
            settings.yandex_csv_direct_login,
            settings.yandex_csv_metrika_counter_id,
        ),
        (
            "urpase",
            settings.yandex_urpase_oauth_token,
            settings.yandex_urpase_direct_login,
            settings.yandex_urpase_metrika_counter_id,
        ),
    ]
    result = [
        (
            key,
            real.RealYandexDirectAdapter(oauth_token=token, direct_login=login),
            real.RealYandexMetrikaAdapter(oauth_token=token, counter_id=counter),
        )
        for key, token, login, counter in configured
        if token and (login or counter)
    ]
    if not result and settings.yandex_oauth_token:
        result.append(("", get_yandex_direct(), get_yandex_metrika()))
    return result


def get_calltouch() -> CalltouchAdapter:
    return real.RealCalltouchAdapter() if _is_real() else mock.MockCalltouchAdapter()


def get_moysklad() -> MoyskladAdapter:
    if not _is_real():
        return mock.MockMoyskladAdapter()
    # Если задан DSN реплики `mpdb` — первичный источник БД, резерв — API МойСклад.
    if (settings.moysklad_pg_dsn or "").strip():
        return real.FallbackMoyskladAdapter()
    return real.RealMoyskladAdapter()
