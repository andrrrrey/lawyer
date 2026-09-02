"""Детерминированный движок регламента (без LLM).

По данным сделок (этап, метки времени, задачи, поля) и настройкам регламента
вычисляет нарушения: просрочка первого контакта, зависшие сделки, лиды без
повторного касания, сделки без задачи, незаполненные поля, дубли. Оценочные
случаи (спам/отказ «для чистоты воронки») подсвечиваются эвристикой и выносятся
на решение руководителя — автоклассификации они не поддаются (раздел 3.1 ТЗ).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models import Deal
from app.services.calendar import (
    WorkSchedule,
    business_minutes,
    calendar_days,
    format_business,
    format_days,
)

TERMINAL_STAGES = {"Оплачено", "Успешно реализовано", "Отказ", "Спам"}
NEW_STAGES = {"Новое обращение", "Новый заказ"}

# Устойчивое распознавание типа этапа: реальные сделки Битрикс приходят с
# кодами стадий (C10:NEW, LOSE, WON…) или названиями воронки Заказчика, которые
# не совпадают с демо-набором. Поэтому дополнительно матчим по ключевым словам.
_TERMINAL_KEYS = ("отказ", "спам", "успешно", "реализ", "оплач", "заверш",
                  "won", "lose", "fail", "success")
_NEW_KEYS = ("новое обращение", "новый заказ")


def is_terminal_stage(stage: str | None) -> bool:
    if stage in TERMINAL_STAGES:
        return True
    s = (stage or "").lower()
    return any(k in s for k in _TERMINAL_KEYS)


def is_new_stage(stage: str | None) -> bool:
    if stage in NEW_STAGES:
        return True
    s = (stage or "").lower()
    return s.endswith("new") or any(k in s for k in _NEW_KEYS)

KIND = {
    "overdue_contact": ("Просрочка первого контакта", "t-red"),
    "no_task": ("Сделка без задачи", "t-amber"),
    "stuck": ("Зависшая сделка", "t-red"),
    "no_recontact": ("Лид без повторного касания", "t-amber"),
    "fields": ("Не заполнены обязательные поля", "t-amber"),
    "dup": ("Возможный дубль", "t-blue"),
    "no_reason": ("Отказ без причины", "t-red"),
    "refusal": ("Отказ «для чистоты воронки»", "t-violet"),
    "spam": ("Подозрительный перевод в «Спам»", "t-violet"),
}

# Подписи сопоставляемых пользовательских полей (для сообщений о нарушениях).
_CUSTOM_LABELS = {
    "refuse_reason": "Причина отказа", "client_type": "Тип клиента",
    "subject": "Суть запроса", "timeline": "Сроки", "product": "Товары/категории",
    "cost": "Себестоимость сделки",
}

# Этап сделки → правило задачи (task_rules), определяющее обязательность задачи.
# Ключи включают как демо-названия, так и названия этапов из регламента Заказчика.
STAGE_TASK_RULE = {
    "Новое обращение": "Новый лид",
    "Новый заказ": "Новый лид",
    "Квалификация": "Квалификация",
    "Обращение взято в работу / Квалификация": "Квалификация",
    "Взято в работу": "Квалификация",
    "Ожидание заказа": "КП отправлено",
    "Ожидание заказа / Квалифицирован": "КП отправлено",
    "Счёт на предоплату": "Счёт выставлен",
    "Счет на предоплату": "Счёт выставлен",
}

# Короткие подписи обязательных полей и предикаты их заполнения.
_FIELD_SHORT = {"Сумма сделки": "Сумма", "UTM-метки": "UTM"}
# Legacy-профиль демо; согласованный профиль из SLA.xlsx переопределяет на 10.
RECONTACT_DAYS = 2


@dataclass
class Config:
    """Разобранные настройки регламента."""

    first_contact_min: int
    stuck_days: int
    task_rules: dict[str, bool]
    req_fields: list[str]
    dup_key: str
    schedule: WorkSchedule
    highlight_spam: bool
    highlight_refusal: bool
    refuse_reason_mapped: bool
    required_custom: list[tuple[str, str]]
    recontact_days: int
    require_planned_task: bool

    @classmethod
    def parse(cls, data: dict) -> Config:
        thresholds = {t["n"]: t for t in data.get("thresholds", [])}
        fc = thresholds.get("Первый контакт", {}).get("v", 15)
        task_rules = {r["n"]: bool(r["on"]) for r in data.get("task_rules", [])}
        req_fields = [name for name, on in data.get("req_fields", []) if on]
        evaluative = data.get("evaluative", {})
        field_map = data.get("field_map") or {}
        fm_fields = field_map.get("fields") or {}
        # Обязательные пользовательские поля: сопоставлены И отмечены как обязательные.
        required_custom = [
            (k, _CUSTOM_LABELS.get(k, k))
            for k in (field_map.get("required") or []) if k in fm_fields
        ]
        sla_rules = {
            str(rule.get("key")): rule
            for rule in (data.get("sla_profile") or {}).get("rules", [])
            if rule.get("enabled", True)
        }
        if "first_touch" in sla_rules:
            fc = sla_rules["first_touch"].get("minutes", fc)
        return cls(
            first_contact_min=int(fc),
            stuck_days=int(evaluative.get("stuck_days", 5)),
            task_rules=task_rules,
            req_fields=req_fields,
            dup_key=data.get("dup_rule", {}).get("value", "По номеру телефона"),
            schedule=WorkSchedule.from_config(data.get("schedule")),
            highlight_spam=bool(evaluative.get("highlight_spam", True)),
            highlight_refusal=bool(evaluative.get("highlight_refusal", True)),
            refuse_reason_mapped="refuse_reason" in fm_fields,
            required_custom=required_custom,
            recontact_days=int(
                sla_rules.get("no_contact", {}).get("days", RECONTACT_DAYS)
            ),
            require_planned_task="planned_task" in sla_rules,
        )


def _has_open_task(deal: Deal) -> bool:
    # Незакрытое «следующее действие»: локальная задача (кнопка «Поставить задачу»
    # / демо-сид) ИЛИ открытая задача/дело из Битрикс24 (флаг has_open_action).
    return bool(deal.has_open_action) or any(t.status == "open" for t in deal.tasks)


def _missing_fields(deal: Deal, req_fields: list[str]) -> list[str]:
    present = {
        "Телефон": bool(deal.phone),
        "Источник": bool(deal.src),
        "UTM-метки": bool(deal.utm),
        "Сумма сделки": deal.amount > 0,
        "Ответственный": bool(deal.mgr) and deal.mgr != "—",
        "Товар / бренд": True,
        "Регион": True,
        "Комментарий": True,
    }
    return [_FIELD_SHORT.get(f, f) for f in req_fields if not present.get(f, True)]


def _dup_value(deal: Deal, dup_key: str) -> str | None:
    if "e-mail" in dup_key and "телефон" not in dup_key:
        return deal.email
    return deal.phone


def _src_label(deal: Deal) -> str:
    """Читаемый источник: сперва SOURCE_ID; иначе — имя кампании из UTM-строки."""
    if deal.src:
        return deal.src
    camp = deal.campaign or ""
    if "name:" in camp:  # UTM вида geo:...|system:...|name:<кампания>
        camp = camp.split("name:", 1)[1].split("|")[0]
    camp = camp.strip()
    return (camp[:40] + "…" if len(camp) > 40 else camp) or "—"


def _mk(deal: Deal, ptype: str, *, over: bool, sla: str, norm: str, amount: int, ai: str,
        category: str = "regular") -> dict:
    label, cls = KIND[ptype]
    severity = "review" if category == "review" else ("over" if over else "warn")
    return {
        "severity": severity, "category": category, "ptype": ptype,
        "kind_label": label, "kind_class": cls,
        "name": f"{deal.name} · {deal.ref}" if deal.ref else deal.name,
        "ref": deal.ref, "mgr": deal.mgr, "src": _src_label(deal),
        "deal_key": f"{deal.crm_source}:{deal.entity_type}:{deal.external_id or deal.id}",
        "norm": norm, "sla": sla, "over": over, "amount": amount, "ai": ai,
    }


def evaluate(deals: list[Deal], config_data: dict, now: datetime) -> dict:
    """Возвращает {'regular': [...], 'review': [...]} нарушений."""
    cfg = Config.parse(config_data)
    sched = cfg.schedule

    # Карта телефонов для поиска дублей (первая встреченная сделка — эталон).
    seen_key: dict[str, Deal] = {}
    for d in sorted(deals, key=lambda x: x.position):
        if is_terminal_stage(d.stage):
            continue
        key = _dup_value(d, cfg.dup_key)
        if key and key not in seen_key:
            seen_key[key] = d

    regular: list[dict] = []
    review: list[dict] = []

    for deal in sorted(deals, key=lambda x: x.position):
        stage = deal.stage or ""
        terminal = is_terminal_stage(stage)
        low = stage.lower()
        is_refusal = "отказ" in low or "lose" in low or "fail" in low

        # --- Отказ без причины (регулярное нарушение; до пропуска терминальных) ---
        if is_refusal and cfg.refuse_reason_mapped and not (deal.custom or {}).get("refuse_reason"):
            regular.append(_mk(
                deal, "no_reason", over=True, sla="—", norm="причина отказа не указана",
                amount=0,
                ai="Сделка переведена в «Отказ» без причины — нарушение регламента "
                   "(перевод в отказ обязателен только с причиной).",
            ))

        # --- Оценочные (эвристика, решение за руководителем) ---
        if ("отказ" in low or stage == "Отказ") and cfg.highlight_refusal and not deal.call:
            if deal.created_at and deal.last_activity_at:
                if business_minutes(deal.created_at, deal.last_activity_at, sched) < 10:
                    review.append(_mk(
                        deal, "refusal", over=False, sla="—", norm="", amount=0,
                        category="review",
                        ai="Отказ проставлен вскоре после лида без звонка. "
                           "Автоклассификации не поддаётся — вынесено на проверку.",
                    ))
                    continue
        if ("спам" in low or stage == "Спам") and cfg.highlight_spam and deal.call:
            review.append(_mk(
                deal, "spam", over=False, sla="—", norm="", amount=0, category="review",
                ai="Был активный диалог, затем перевод в «Спам». Похоже на «чистку "
                   "воронки». Решение — за руководителем.",
            ))
            continue

        if terminal:
            continue

        # --- Регулярные нарушения (приоритет сверху вниз, одно на сделку) ---
        # 1. Просрочка первого контакта
        if is_new_stage(stage) and deal.first_contact_at is None and deal.created_at:
            elapsed = business_minutes(deal.created_at, now, sched)
            if elapsed >= cfg.first_contact_min:
                el = format_business(elapsed, sched)
                regular.append(_mk(
                    deal, "overdue_contact", over=elapsed > cfg.first_contact_min,
                    sla=el, norm=f"норматив {cfg.first_contact_min} мин", amount=0,
                    ai=f"Лид в рабочее время, первого контакта нет {el}. "
                       "Требуется немедленный звонок.",
                ))
                continue

        # 2. Зависшая сделка (нет движения по этапу дольше норматива)
        if deal.stage_entered_at:
            days = calendar_days(deal.stage_entered_at, now)
            if days > cfg.stuck_days:
                regular.append(_mk(
                    deal, "stuck", over=True, sla=format_days(days),
                    norm=f"без движения {days} дн · норматив {cfg.stuck_days}",
                    amount=deal.amount,
                    ai="Нет движения по этапу и повторных касаний. Высокий риск потери.",
                ))
                continue

        # 3. Сделка без задачи на этапе, где задача обязательна
        rule_name = STAGE_TASK_RULE.get(stage)
        task_required = cfg.require_planned_task or bool(
            rule_name and cfg.task_rules.get(rule_name)
        )
        if task_required and not _has_open_task(deal):
            elapsed = business_minutes(deal.stage_entered_at or deal.created_at or now, now, sched)
            regular.append(_mk(
                deal, "no_task", over=elapsed > sched.day_minutes(),
                sla=format_business(elapsed, sched), norm=f"этап «{stage}»",
                amount=deal.amount,
                ai="На этапе, где задача обязательна по регламенту, задача отсутствует.",
            ))
            continue

        # 4. Лид без повторного касания
        if not is_new_stage(stage) and deal.first_contact_at and deal.last_activity_at:
            days = calendar_days(deal.last_activity_at, now)
            if days >= cfg.recontact_days:
                regular.append(_mk(
                    deal, "no_recontact", over=False, sla=format_days(days),
                    norm=f"{format_days(days)} без касания", amount=deal.amount,
                    ai="Первый контакт был, дальнейших касаний нет.",
                ))
                continue

        # 5. Возможный дубль
        key = _dup_value(deal, cfg.dup_key)
        if key and seen_key.get(key) is not deal:
            other = seen_key[key]
            regular.append(_mk(
                deal, "dup", over=False, sla="—",
                norm=f"совпадение телефона с {other.ref}", amount=0,
                ai=f"Телефон совпадает с существующей сделкой ({other.ref}). "
                   "Проверьте объединение.",
            ))
            continue

        # 6. Не заполнены обязательные поля (стандартные + сопоставленные кастомные)
        missing = _missing_fields(deal, cfg.req_fields)
        for key, label in cfg.required_custom:
            if not (deal.custom or {}).get(key):
                missing.append(label)
        if missing:
            regular.append(_mk(
                deal, "fields", over=False, sla="—",
                norm=f"нет: {', '.join(missing)}", amount=0,
                ai="Без обязательных полей сделка не попадёт в расчёт выручки и маржи.",
            ))
            continue

    return {"regular": regular, "review": review}
