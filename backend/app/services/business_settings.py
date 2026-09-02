"""Чтение, проверка и сохранение бизнес-настроек единого дашборда."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusinessSettings
from app.seeds.business import BUSINESS_SETTINGS

_ARTICLE_OPERATIONS = {"income", "refund", "exclude"}


async def get_settings(session: AsyncSession) -> dict[str, Any]:
    row = await session.scalar(select(BusinessSettings).where(BusinessSettings.id == 1))
    if row is None or not row.data:
        return deepcopy(BUSINESS_SETTINGS)
    return deepcopy(row.data)


async def save_settings(session: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_settings(data)
    row = await session.scalar(select(BusinessSettings).where(BusinessSettings.id == 1))
    if row is None:
        row = BusinessSettings(id=1, data=normalized)
        session.add(row)
    else:
        row.data = normalized
    await session.commit()
    return deepcopy(normalized)


def validate_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Проверяет ссылки справочников и нормализует строки без нечёткого поиска."""
    if not isinstance(data, dict):
        raise ValueError("Настройки должны быть JSON-объектом")

    result = deepcopy(data)
    entities = _list(result, "legal_entities")
    sources = _list(result, "crm_sources")
    funnels = _list(result, "funnels")
    departments = _list(result, "departments")
    employees = _list(result, "employees")
    profiles = _list(result, "sla_profiles")
    _list(result, "plans")

    entity_keys = _unique_keys(entities, "legal_entities")
    source_keys = _unique_keys(sources, "crm_sources")
    department_keys = _unique_keys(departments, "departments")
    employee_keys = _unique_keys(employees, "employees")
    profile_keys = _unique_keys(profiles, "sla_profiles")

    for entity in entities:
        entity["name"] = _required_text(entity.get("name"), "Наименование юрлица")
        entity["inn"] = str(entity.get("inn", "")).strip()
        entity["kpp"] = str(entity.get("kpp", "")).strip()
        articles = entity.get("dds_articles", [])
        if not isinstance(articles, list):
            raise ValueError(f"dds_articles юрлица {entity['key']} должен быть списком")
        article_names: set[str] = set()
        for article in articles:
            if not isinstance(article, dict):
                raise ValueError("Статья ДДС должна быть объектом")
            # Только удаляем случайные пробелы по краям. Регистр и написание
            # сохраняются для точного сопоставления с ответом 1С.
            name = _required_text(article.get("name"), "Наименование статьи ДДС")
            if name in article_names:
                raise ValueError(f"Повтор статьи ДДС «{name}» у {entity['name']}")
            article_names.add(name)
            article["name"] = name
            operation = str(article.get("operation", "income")).strip()
            if operation not in _ARTICLE_OPERATIONS:
                raise ValueError(f"Недопустимая операция статьи ДДС: {operation}")
            article["operation"] = operation

    for funnel in funnels:
        if str(funnel.get("legal_entity_key", "")) not in entity_keys:
            raise ValueError("Воронка ссылается на неизвестное юридическое лицо")
        if str(funnel.get("crm_source", "")) not in source_keys:
            raise ValueError("Воронка ссылается на неизвестный источник Bitrix24")
        profile = str(funnel.get("sla_profile_key", "default"))
        if profile not in profile_keys:
            raise ValueError("Воронка ссылается на неизвестный профиль SLA")

    for employee in employees:
        entity_key = str(employee.get("legal_entity_key", ""))
        if entity_key and entity_key not in entity_keys:
            raise ValueError("Сотрудник ссылается на неизвестное юридическое лицо")
        department_key = str(employee.get("department_key", ""))
        if department_key and department_key not in department_keys:
            raise ValueError("Сотрудник ссылается на неизвестный отдел")

    for plan in result["plans"]:
        employee_key = str(plan.get("employee_key", ""))
        if employee_key and employee_key not in employee_keys:
            raise ValueError("План ссылается на неизвестного сотрудника")
        entity_key = str(plan.get("legal_entity_key", ""))
        if entity_key and entity_key not in entity_keys:
            raise ValueError("План ссылается на неизвестное юридическое лицо")

    result["schema_version"] = 1
    return result


def legal_entity_for_funnel(data: dict[str, Any], crm_source: str, funnel_id: str) -> str:
    """Возвращает юрлицо по точному сопоставлению источник × ID воронки."""
    for funnel in data.get("funnels", []):
        if (
            str(funnel.get("crm_source")) == crm_source
            and str(funnel.get("external_id")) == str(funnel_id)
            and funnel.get("enabled", True)
        ):
            return str(funnel.get("legal_entity_key", ""))
    return ""


def sla_profile_for_funnel(
    data: dict[str, Any], crm_source: str, funnel_id: str
) -> dict[str, Any] | None:
    profile_key: str | None = None
    for funnel in data.get("funnels", []):
        if (
            str(funnel.get("crm_source")) == crm_source
            and str(funnel.get("external_id")) == str(funnel_id)
            and funnel.get("enabled", True)
        ):
            profile_key = str(funnel.get("sla_profile_key") or "default")
            break
    if profile_key is None:
        return None
    return next(
        (
            profile
            for profile in data.get("sla_profiles", [])
            if profile.get("key") == profile_key and profile.get("enabled", True)
        ),
        None,
    )


def receipt_article_operation(data: dict[str, Any], entity_key: str, name: str) -> str | None:
    """Точное сопоставление статьи ДДС после удаления краевых пробелов."""
    needle = name.strip()
    for entity in data.get("legal_entities", []):
        if entity.get("key") != entity_key:
            continue
        for article in entity.get("dds_articles", []):
            if article.get("enabled", True) and str(article.get("name", "")).strip() == needle:
                return str(article.get("operation", "income"))
    return None


def _list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"Поле {key} должно быть списком")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Элементы {key} должны быть объектами")
    return value


def _unique_keys(items: list[dict[str, Any]], label: str) -> set[str]:
    keys: set[str] = set()
    for item in items:
        key = str(item.get("key", "")).strip()
        if not key:
            raise ValueError(f"Пустой key в {label}")
        if key in keys:
            raise ValueError(f"Повтор key «{key}» в {label}")
        item["key"] = key
        keys.add(key)
    return keys


def _required_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} не может быть пустым")
    return text
