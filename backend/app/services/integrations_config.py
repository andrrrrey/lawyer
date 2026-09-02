"""Конфигурация доступов к интеграциям через UI.

Единый реестр полей (PROVIDERS) описывает, какие креды нужны каждому источнику.
Значения хранятся в БД (модель IntegrationSettings, одна строка) и накатываются
поверх переменных окружения на объект app.core.config.settings — так интеграции
настраиваются без правки .env и без перезапуска контейнера.

Секреты наружу отдаются замаскированными (`•••• + хвост`); при сохранении пустое
значение секрета трактуется как «оставить как есть» (чтобы не затирать токен
случайно), поэтому очистка секрета выполняется отдельным флагом clear.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models import IntegrationSettings

logger = get_logger("lawyer.integrations")


@dataclass(frozen=True)
class Field:
    key: str            # имя атрибута в Settings (= ключ в data)
    label: str          # подпись в интерфейсе
    hint: str = ""      # подсказка «где взять»
    secret: bool = True  # маскировать ли значение наружу
    placeholder: str = ""


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    subtitle: str
    docs: str
    fields: list[Field] = field(default_factory=list)


PROVIDERS: list[Provider] = [
    Provider(
        key="bitrix_box",
        name="Bitrix24 · коробочная версия",
        subtitle="Первый источник CRM; воронки распределяются в настройках",
        docs="Портал → «Разработчикам» → «Другое» → «Входящий вебхук»",
        fields=[
            Field(
                "bitrix_box_webhook_url",
                "URL входящего вебхука",
                "Права на чтение CRM и запись задач. Пример: "
                "https://<portal>.bitrix24.ru/rest/1/<код>/",
                secret=True,
                placeholder="https://<portal>.bitrix24.ru/rest/1/<код>/",
            ),
            Field(
                "bitrix_box_inbound_token",
                "Токен исходящих вебхуков",
                "Необязательно. Нужен только если настраиваете «Исходящий вебхук» "
                "Битрикс24 (push событий): URL обработчика в Битрикс — "
                "https://<ваш-домен>/api/webhooks/bitrix24, а сюда впишите «Токен "
                "приложения» из той же формы.",
                secret=True,
            ),
        ],
    ),
    Provider(
        key="bitrix_cloud",
        name="Bitrix24 · облачная версия",
        subtitle="Второй источник CRM; воронки распределяются в настройках",
        docs="Портал → «Разработчикам» → «Другое» → «Входящий вебхук»",
        fields=[
            Field(
                "bitrix_cloud_webhook_url",
                "URL входящего вебхука",
                "Права на чтение CRM и запись задач.",
                secret=True,
                placeholder="https://<portal>.bitrix24.ru/rest/1/<код>/",
            ),
            Field(
                "bitrix_cloud_inbound_token",
                "Токен исходящих вебхуков",
                "Необязательно; используется для проверки push-событий.",
                secret=True,
            ),
        ],
    ),
    Provider(
        key="yandex_uo",
        name="Яндекс · ЮО",
        subtitle="Директ и Метрика юридического лица ЮО",
        docs="OAuth Яндекса + доступ к API Директа и счётчику Метрики",
        fields=[
            Field("yandex_uo_oauth_token", "OAuth-токен", secret=True),
            Field("yandex_uo_direct_login", "Логин Директа", secret=False),
            Field(
                "yandex_uo_metrika_counter_id", "Номер счётчика Метрики", secret=False
            ),
        ],
    ),
    Provider(
        key="yandex_csv",
        name="Яндекс · ЦСВ",
        subtitle="Директ и Метрика юридического лица ЦСВ",
        docs="OAuth Яндекса + доступ к API Директа и счётчику Метрики",
        fields=[
            Field("yandex_csv_oauth_token", "OAuth-токен", secret=True),
            Field("yandex_csv_direct_login", "Логин Директа", secret=False),
            Field(
                "yandex_csv_metrika_counter_id", "Номер счётчика Метрики", secret=False
            ),
        ],
    ),
    Provider(
        key="yandex_urpase",
        name="Яндекс · УрПАСЭ",
        subtitle="Директ и Метрика юридического лица УрПАСЭ",
        docs="OAuth Яндекса + доступ к API Директа и счётчику Метрики",
        fields=[
            Field("yandex_urpase_oauth_token", "OAuth-токен", secret=True),
            Field("yandex_urpase_direct_login", "Логин Директа", secret=False),
            Field(
                "yandex_urpase_metrika_counter_id",
                "Номер счётчика Метрики",
                secret=False,
            ),
        ],
    ),
    Provider(
        key="onec",
        name="1С:УНФ",
        subtitle="Фактические поступления и статьи ДДС",
        docs="HTTP-сервис из ТЗ, авторизация Basic Authentication",
        fields=[
            Field(
                "onec_endpoint",
                "Endpoint HTTP-сервиса",
                "Полный адрес метода получения поступлений из 1С:УНФ.",
                secret=False,
                placeholder="http://1c.example.local/path",
            ),
            Field(
                "onec_username",
                "Логин Basic Authentication",
                "Пользователь HTTP-сервиса 1С.",
                secret=False,
            ),
            Field(
                "onec_password",
                "Пароль Basic Authentication",
                "Пароль хранится в настройках и не выводится в журналы.",
                secret=True,
            ),
        ],
    ),
    Provider(
        key="llm",
        name="AI-слой (LLM)",
        subtitle="Облачная модель для интерпретации",
        docs="OpenAI-совместимый эндпоинт: base URL, ключ, идентификатор модели",
        fields=[
            Field("llm_api_key", "API-ключ", "Ключ доступа к LLM API.", secret=True),
            Field(
                "llm_base_url",
                "Base URL",
                "Например, https://api.openai.com/v1 или иной совместимый эндпоинт.",
                secret=False,
                placeholder="https://api.openai.com/v1",
            ),
            Field(
                "llm_model",
                "Идентификатор модели",
                "Например, gpt-4o-mini.",
                secret=False,
                placeholder="gpt-4o-mini",
            ),
        ],
    ),
]

# Плоский индекс key → Field (для валидации/маскирования).
_FIELD_INDEX: dict[str, Field] = {f.key: f for p in PROVIDERS for f in p.fields}
FIELD_KEYS: frozenset[str] = frozenset(_FIELD_INDEX)

# Служебные ключи в JSON-данных строки (не входят в FIELD_KEYS, не трактуются как
# креды): источник данных, сохранённые результаты проверок, статус пересчёта,
# сопоставление пользовательских полей Битрикс.
_DS_KEY = "__data_source__"
_CHECKS_KEY = "__checks__"
_RECOMPUTE_KEY = "__recompute__"
_FIELD_MAP_KEY = "__field_map__"

# Семантические поля регламента, которые можно сопоставить с полями воронки
# Битрикс на странице «Интеграции». enables — что даёт заполнение поля.
FIELD_MAP_TARGETS: list[dict] = [
    {"key": "refuse_reason", "label": "Причина отказа",
     "hint": "Включает контроль «перевод в отказ без причины»."},
    {"key": "client_type", "label": "Тип клиента",
     "hint": "Частное лицо / мастер / дизайнер / компания и т.п."},
    {"key": "subject", "label": "Суть запроса",
     "hint": "Что именно требуется клиенту."},
    {"key": "timeline", "label": "Сроки",
     "hint": "Ориентир по срокам клиента."},
    {"key": "product", "label": "Товары / категории",
     "hint": "Интересующие товары или категории."},
    {"key": "cost", "label": "Себестоимость сделки",
     "hint": "Числовое поле себестоимости сделки — включает расчёт маржи "
             "(маржа = выручка − себестоимость по выигранным сделкам)."},
]
_FIELD_MAP_KEYS = frozenset(t["key"] for t in FIELD_MAP_TARGETS)


def _default_field_map() -> dict:
    return {"fields": {}, "required": []}


async def get_field_map(session: AsyncSession) -> dict:
    """Текущее сопоставление полей: {'fields': {ключ: код Битрикс}, 'required': [ключи]}."""
    row = await _load_row(session)
    if row and isinstance(row.data, dict):
        fm = row.data.get(_FIELD_MAP_KEY)
        if isinstance(fm, dict):
            fields = {k: v for k, v in (fm.get("fields") or {}).items()
                      if k in _FIELD_MAP_KEYS and v}
            required = [k for k in (fm.get("required") or []) if k in _FIELD_MAP_KEYS]
            return {"fields": fields, "required": required}
    return _default_field_map()


async def save_field_map(session: AsyncSession, fields: dict, required: list) -> dict:
    """Сохраняет сопоставление полей Битрикс (только известные семантические ключи)."""
    clean_fields = {k: str(v).strip() for k, v in (fields or {}).items()
                    if k in _FIELD_MAP_KEYS and str(v or "").strip()}
    clean_required = [k for k in (required or []) if k in _FIELD_MAP_KEYS]
    row = await _load_or_create_row(session)
    data = dict(row.data) if isinstance(row.data, dict) else {}
    data[_FIELD_MAP_KEY] = {"fields": clean_fields, "required": clean_required}
    row.data = data
    await session.commit()
    return {"fields": clean_fields, "required": clean_required}


async def _load_row(session: AsyncSession) -> IntegrationSettings | None:
    return await session.get(IntegrationSettings, 1)


async def _load_or_create_row(session: AsyncSession) -> IntegrationSettings:
    row = await _load_row(session)
    if row is None:
        row = IntegrationSettings(id=1, data={})
        session.add(row)
    return row


async def save_check_result(session: AsyncSession, provider: str, result: dict) -> None:
    """Сохраняет последний результат проверки провайдера (переживает перезагрузку)."""
    row = await _load_or_create_row(session)
    data = dict(row.data) if isinstance(row.data, dict) else {}
    checks = dict(data.get(_CHECKS_KEY) or {})
    checks[provider] = {
        "provider": provider,
        "status": result.get("status"),
        "message": result.get("message", ""),
        "detail": result.get("detail", ""),
        "checked_at": result.get("checked_at", ""),
    }
    data[_CHECKS_KEY] = checks
    row.data = data
    await session.commit()


def _default_recompute_status() -> dict:
    return {
        "state": "idle", "step": "", "started_at": None, "finished_at": None,
        "mode": None, "error": None, "sources": {}, "stats": {},
    }


async def get_recompute_status(session: AsyncSession) -> dict:
    row = await _load_row(session)
    if row and isinstance(row.data, dict):
        stored = row.data.get(_RECOMPUTE_KEY)
        if isinstance(stored, dict):
            return {**_default_recompute_status(), **stored}
    return _default_recompute_status()


async def set_recompute_status(session: AsyncSession, status: dict) -> None:
    row = await _load_or_create_row(session)
    data = dict(row.data) if isinstance(row.data, dict) else {}
    data[_RECOMPUTE_KEY] = status
    row.data = data
    await session.commit()


async def merge_recompute_status(session: AsyncSession, patch: dict) -> dict:
    current = await get_recompute_status(session)
    current.update(patch)
    await set_recompute_status(session, current)
    return current


async def load_overrides(session: AsyncSession) -> dict[str, str]:
    """Значения кредов из БД (без маскирования). Пусто, если строки ещё нет."""
    row = await _load_row(session)
    if not row or not isinstance(row.data, dict):
        return {}
    return {k: v for k, v in row.data.items() if k in FIELD_KEYS}


async def load_data_source(session: AsyncSession) -> str:
    """Источник данных из БД (mock|real), иначе — текущее значение из settings/env."""
    row = await _load_row(session)
    if row and isinstance(row.data, dict):
        stored = row.data.get(_DS_KEY)
        if stored in ("mock", "real"):
            return stored
    return settings.data_source


def _current_value(overrides: dict[str, str], key: str) -> str:
    """Эффективное значение: оверрайд из БД, иначе — текущее из settings/env."""
    if key in overrides:
        return overrides[key] or ""
    return str(getattr(settings, key, "") or "")


def _masked(value: str) -> str:
    if not value:
        return ""
    tail = value[-4:] if len(value) > 4 else ""
    return f"••••{tail}"


async def get_config(session: AsyncSession) -> dict:
    """Структура для UI: провайдеры, поля (маскированные), признаки заполнения."""
    row = await _load_row(session)
    raw = row.data if row and isinstance(row.data, dict) else {}
    overrides = {k: v for k, v in raw.items() if k in FIELD_KEYS}
    stored_ds = raw.get(_DS_KEY)
    data_source = stored_ds if stored_ds in ("mock", "real") else settings.data_source

    # AI считается подключённым при заданных ключе и base URL (как в llm.is_configured).
    ai_configured = bool(
        _current_value(overrides, "llm_api_key") and _current_value(overrides, "llm_base_url")
    )

    # Сохранённые результаты последних проверок (чтобы статус переживал перезагрузку).
    stored_checks = raw.get(_CHECKS_KEY) if isinstance(raw.get(_CHECKS_KEY), dict) else {}
    fm = raw.get(_FIELD_MAP_KEY) if isinstance(raw.get(_FIELD_MAP_KEY), dict) else {}
    field_map = {
        "fields": {k: v for k, v in (fm.get("fields") or {}).items()
                   if k in _FIELD_MAP_KEYS and v},
        "required": [k for k in (fm.get("required") or []) if k in _FIELD_MAP_KEYS],
    }

    providers_out: list[dict] = []
    for p in PROVIDERS:
        fields_out: list[dict] = []
        filled_count = 0
        # Необязательные поля (не влияют на признак «настроено»): доп. логин Директа,
        # токен исходящих Битрикс, DSN реплики МойСклад (ускоритель поверх API).
        _optional = {
            "bitrix_box_inbound_token",
            "bitrix_cloud_inbound_token",
            "yandex_uo_direct_login",
            "yandex_csv_direct_login",
            "yandex_urpase_direct_login",
        }
        required = [f for f in p.fields if f.key not in _optional]
        for f in p.fields:
            raw = _current_value(overrides, f.key)
            is_filled = bool(raw)
            if is_filled and f in required:
                filled_count += 1
            fields_out.append({
                "key": f.key,
                "label": f.label,
                "hint": f.hint,
                "secret": f.secret,
                "placeholder": f.placeholder,
                "filled": is_filled,
                # Маска остаётся неизменным черновиком на фронтенде и поэтому не
                # отправляется назад, пока пользователь не введёт новое значение.
                "value": _masked(raw) if f.secret else raw,
            })
        configured = filled_count >= len(required) if required else False
        providers_out.append({
            "key": p.key,
            "name": p.name,
            "subtitle": p.subtitle,
            "docs": p.docs,
            "configured": configured,
            "last_check": stored_checks.get(p.key),
            "fields": fields_out,
        })

    return {
        "data_source": data_source,
        "ai_configured": ai_configured,
        "providers": providers_out,
        "field_map": field_map,
        "field_targets": FIELD_MAP_TARGETS,
    }


def _apply_to_settings(values: dict[str, str]) -> None:
    """Накатывает значения на живой объект настроек (без валидации присваивания)."""
    for key, value in values.items():
        if key in FIELD_KEYS:
            setattr(settings, key, value or "")


async def apply_overrides_from_db(session: AsyncSession) -> int:
    """Накат из БД поверх env: креды + источник данных. Возвращает число полей.

    Вызывается на старте каждого процесса (api/worker/ingest), чтобы сохранённые
    через UI доступы и режим применялись одинаково во всех воркерах."""
    row = await _load_row(session)
    if not row or not isinstance(row.data, dict):
        return 0
    overrides = {k: v for k, v in row.data.items() if k in FIELD_KEYS}
    if overrides:
        _apply_to_settings(overrides)
    stored_ds = row.data.get(_DS_KEY)
    if stored_ds in ("mock", "real"):
        settings.data_source = stored_ds  # type: ignore[assignment]
    return len(overrides)


async def save_config(
    session: AsyncSession,
    *,
    values: dict[str, str] | None = None,
    clear: list[str] | None = None,
    data_source: str | None = None,
) -> dict:
    """Сохраняет доступы в БД и накатывает на живой settings.

    - values: {ключ: значение}. Присылаются только изменённые поля; пустая строка
      очищает значение, непустая — задаёт новое.
    - clear: список ключей, которые нужно очистить принудительно.
    - data_source: mock | real (переключение источника данных).
    """
    row = await _load_row(session)
    data: dict[str, str] = dict(row.data) if row and isinstance(row.data, dict) else {}
    # Прежний источник данных — чтобы отследить переключение mock↔real.
    old_ds = data.get(_DS_KEY) if data.get(_DS_KEY) in ("mock", "real") else settings.data_source

    applied: dict[str, str] = {}

    # Поля предзаполнены реальными значениями, поэтому фронтенд присылает только
    # изменённые: пустая строка = очистка, непустая = новое значение.
    for key, value in (values or {}).items():
        if key not in FIELD_KEYS:
            continue
        text = (value or "").strip()
        data[key] = text
        applied[key] = text

    for key in clear or []:
        if key in FIELD_KEYS:
            data[key] = ""
            applied[key] = ""

    # Источник данных храним в служебном ключе — чтобы он переживал перезапуск и
    # был одинаков во всех воркерах (в память пишем ниже).
    if data_source in ("mock", "real"):
        data[_DS_KEY] = data_source

    if row is None:
        row = IntegrationSettings(id=1, data=data)
        session.add(row)
    else:
        row.data = data

    await session.commit()

    # Немедленно активируем сохранённое в текущем процессе.
    _apply_to_settings(applied)
    if data_source in ("mock", "real"):
        settings.data_source = data_source  # type: ignore[assignment]

    # Переключение режима: боевой — убрать демо; демо — восстановить.
    if data_source in ("mock", "real") and data_source != old_ds:
        from app.services import data_mode
        try:
            if data_source == "real":
                await data_mode.switch_to_real(session)
            else:
                await data_mode.switch_to_mock(session)
        except Exception as exc:  # noqa: BLE001 — сохранение настроек важнее
            logger.warning("Переключение режима данных: %s", exc)

    logger.info(
        "Настройки интеграций сохранены: полей=%d, data_source=%s",
        len(applied), settings.data_source,
    )
    return await get_config(session)
