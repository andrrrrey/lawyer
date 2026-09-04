"""Чтение, проверка и сохранение бизнес-настроек единого дашборда."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusinessSettings
from app.seeds.business import BUSINESS_SETTINGS

_ARTICLE_OPERATIONS = {"income", "refund", "exclude"}
_PLAN_SCOPES = {"company", "department", "employee"}
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


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
        expected = funnel.get("expected_payment_stages", ["Заключение Контракта"])
        if not isinstance(expected, list):
            raise ValueError("Стадии ожидания оплаты должны быть списком")
        funnel["expected_payment_stages"] = [
            str(item).strip()[:128] for item in expected if str(item).strip()
        ]

    for employee in employees:
        crm_source = str(employee.get("crm_source", "")).strip()
        if crm_source and crm_source not in source_keys:
            raise ValueError("Сотрудник ссылается на неизвестный источник Bitrix24")
        employee["crm_source"] = crm_source
        entity_key = str(employee.get("legal_entity_key", ""))
        if entity_key and entity_key not in entity_keys:
            raise ValueError("Сотрудник ссылается на неизвестное юридическое лицо")
        department_key = str(employee.get("department_key", ""))
        if department_key and department_key not in department_keys:
            raise ValueError("Сотрудник ссылается на неизвестный отдел")

    plan_keys: set[tuple[str, str, str, str]] = set()
    for plan in result["plans"]:
        entity_key = str(plan.get("legal_entity_key", ""))
        if entity_key not in entity_keys:
            raise ValueError("План ссылается на неизвестное юридическое лицо")
        scope_type = str(plan.get("scope_type") or "employee")
        scope_key = str(plan.get("scope_key") or plan.get("employee_key") or "")
        if scope_type not in _PLAN_SCOPES:
            raise ValueError("Неизвестный уровень плана")
        if scope_type == "employee" and scope_key not in employee_keys:
            raise ValueError("План ссылается на неизвестного сотрудника")
        if scope_type == "department" and scope_key not in department_keys:
            raise ValueError("План ссылается на неизвестный отдел")
        if not _MONTH_RE.fullmatch(str(plan.get("period") or "")):
            raise ValueError("Период плана должен быть в формате ГГГГ-ММ")
        plan["scope_type"] = scope_type
        plan["scope_key"] = entity_key if scope_type == "company" else scope_key
        plan.pop("employee_key", None)
        identity = (entity_key, scope_type, plan["scope_key"], str(plan["period"]))
        if identity in plan_keys:
            raise ValueError("Для выбранного уровня уже задан план на этот месяц")
        plan_keys.add(identity)
        for metric in ("revenue", "payments", "deals", "calls", "meetings"):
            try:
                value = int(plan.get(metric) or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Показатель плана {metric} должен быть числом") from exc
            if value < 0:
                raise ValueError("Показатели плана не могут быть отрицательными")
            plan[metric] = value

    result["schema_version"] = 1
    return result


def employee_names_for_source(data: dict[str, Any], crm_source: str) -> dict[str, str]:
    """Ручной справочник ID → ФИО для портала Bitrix24.

    Используется как fallback, когда вебхуку не выдан минимальный scope
    ``user_brief`` и метод ``user.get`` недоступен.
    """
    result: dict[str, str] = {}
    for employee in data.get("employees", []):
        source = str(employee.get("crm_source", "")).strip()
        user_id = str(employee.get("bitrix_user_id", "")).strip()
        name = str(employee.get("name", "")).strip()
        if (
            employee.get("enabled", True)
            and user_id
            and name
            and source in ("", crm_source)
        ):
            result[user_id] = name
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


def funnel_name(data: dict[str, Any], crm_source: str, funnel_id: str) -> str:
    """Пользовательское название выбранной в настройках воронки."""
    for funnel in data.get("funnels", []):
        if (
            str(funnel.get("crm_source")) == crm_source
            and str(funnel.get("external_id")) == str(funnel_id)
        ):
            return str(funnel.get("name") or "")
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
