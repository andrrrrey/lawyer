"""Начальные бизнес-настройки Lawyer по согласованному ТЗ и приложениям."""

from __future__ import annotations


def _article(name: str) -> dict:
    return {"name": name, "operation": "income", "enabled": True, "notes": ""}


_COMMON_DDS = [
    "Гонорар успеха (неустойки/штрафы)",
    "Оплата от покупателей",
    "Расчёт по акту выполненных работ ОВЗ",
    "Соглашение",
    "Эквайринг",
    "Эквайринг QR",
    "Экспертиза",
    "Юридические услуги",
]

_UO_DDS = [
    "Гонорар успеха (неустойки/штрафы)",
    "Оплата от покупателей",
    "Расчёт по акту выполненных работ",
    "Расчёт по акту выполненных работ ОВЗ",
    "Рекрутинг",
    "Эквайринг",
    "Эквайринг QR",
    "ЭРобокасса",
    "Юр услуги по банкротству",
    "Юридическая консультация",
    "Юридические услуги",
]


BUSINESS_SETTINGS: dict = {
    "schema_version": 1,
    "legal_entities": [
        {
            "key": "uo",
            "name": "ЮО",
            "inn": "",
            "kpp": "",
            "enabled": True,
            "position": 0,
            "dds_articles": [_article(name) for name in _UO_DDS],
        },
        {
            "key": "csv",
            "name": "ЦСВ",
            "inn": "",
            "kpp": "",
            "enabled": True,
            "position": 1,
            "dds_articles": [_article(name) for name in _COMMON_DDS],
        },
        {
            "key": "urpase",
            "name": "УрПАСЭ",
            "inn": "",
            "kpp": "",
            "enabled": True,
            "position": 2,
            "dds_articles": [_article(name) for name in _COMMON_DDS],
        },
    ],
    # crm_source — внутренний технический ключ. В интерфейсе отдельного
    # «CRM-портала» или выбора портала нет.
    "crm_sources": [
        {"key": "box", "name": "Коробочный Bitrix24", "enabled": True},
        {"key": "cloud", "name": "Облачный Bitrix24", "enabled": True},
    ],
    "funnels": [],
    "departments": [],
    "employees": [],
    "plans": [],
    "sla_profiles": [
        {
            "key": "default",
            "name": "Основной регламент",
            "enabled": True,
            "rules": [
                {
                    "source_number": 1,
                    "key": "first_touch",
                    "name": "Лид взят в работу / первое касание",
                    "description": (
                        "Первое касание не позднее 15 минут. Обращения после окончания "
                        "предыдущего рабочего дня обрабатываются в первый рабочий час."
                    ),
                    "minutes": 15,
                    "enabled": True,
                },
                {
                    "source_number": 2,
                    "key": "dialog_comment",
                    "name": "Информативный комментарий после диалога",
                    "description": "Итог звонка, встречи и договорённостей с клиентом.",
                    "enabled": True,
                },
                {
                    "source_number": 3,
                    "key": "planned_task",
                    "name": "Своевременная запланированная задача",
                    "description": "В сделке есть осмысленное следующее действие со сроком.",
                    "enabled": True,
                },
                {
                    "source_number": 4,
                    "key": "stage_matches_work",
                    "name": "Стадия CRM соответствует фактической работе",
                    "description": "",
                    "enabled": True,
                },
                {
                    "source_number": 5,
                    "key": "no_contact",
                    "name": "Нет контакта с клиентом более 10 дней",
                    "description": (
                        "Исключение: в CRM зафиксирована договорённость связаться позднее."
                    ),
                    "days": 10,
                    "enabled": True,
                },
                {
                    "source_number": 7,
                    "key": "touch_chain",
                    "name": "Цепочка касаний",
                    "description": (
                        "По одному звонку в первые три дня, звонок на пятый день, "
                        "SMS на шестой день."
                    ),
                    "schedule": [
                        {"day": 1, "action": "call"},
                        {"day": 2, "action": "call"},
                        {"day": 3, "action": "call"},
                        {"day": 5, "action": "call"},
                        {"day": 6, "action": "sms"},
                    ],
                    "enabled": True,
                },
            ],
        }
    ],
}
