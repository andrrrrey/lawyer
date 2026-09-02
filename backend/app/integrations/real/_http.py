"""Общий HTTP-слой для боевых адаптеров: ретраи, таймауты, проверка TLS.

Проверка сертификата обязательна (раздел 7.2 ТЗ). Для российских сервисов в
доверенное хранилище контейнера устанавливаются корневой и выпускающий
сертификаты НУЦ Минцифры (см. backend/Dockerfile и docs/DEPLOYMENT.md) —
httpx использует системное хранилище по умолчанию.

Повторяются только временные ошибки (429 и 5xx, сетевые сбои) с экспоненциальной
задержкой 2s→4s→8s→16s; ошибки 4xx возвращаются сразу.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.logging import get_logger

logger = get_logger("lawyer.integrations")

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return isinstance(exc, httpx.TransportError)


@retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    retry=retry_if_exception(_should_retry),
)
def request(
    method: str,
    url: str,
    *,
    client: httpx.Client | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """HTTP-запрос с ретраями по временным ошибкам. 4xx возвращаются без ретрая."""
    own = client is None
    cl = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
    try:
        resp = cl.request(method, url, **kwargs)
        # Временные ошибки → исключение (сработает ретрай); прочее возвращаем.
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        return resp
    finally:
        if own:
            cl.close()
