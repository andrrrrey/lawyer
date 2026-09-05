"""Боевой адаптер Битрикс24 (REST через входящий вебхук).

Читает сделки единой воронки, историю стадий и задачи; ставит задачи
ответственным. Требует вебхук с правами на чтение CRM и запись задач
(BITRIX24_WEBHOOK_URL). Сопоставление конкретных полей воронки (стадии,
источники, UTM) уточняется на портале Заказчика при настройке интеграции.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.real._http import DEFAULT_TIMEOUT, request

logger = get_logger("lawyer.integrations")

_PAGE = 50


def _base(webhook_url: str | None = None) -> str:
    url = webhook_url if webhook_url is not None else settings.bitrix24_webhook_url
    if not url:
        raise RuntimeError("BITRIX24_WEBHOOK_URL не задан")
    return url.rstrip("/")


def _call(
    method: str, params: dict | None = None, webhook_url: str | None = None
) -> list[dict]:
    """Вызывает REST-метод с постраничной выгрузкой (envelope result/next/total)."""
    out: list[dict] = []
    start = 0
    base = _base() if webhook_url is None else _base(webhook_url)
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        while True:
            payload = dict(params or {})
            payload["start"] = start
            resp = request(
                "POST", f"{base}/{method}.json", client=client, json=payload
            )
            data = resp.json()
            # REST Битрикс24 нередко отвечает HTTP 200 даже при отказе. Раньше
            # постраничный клиент трактовал такой конверт как пустой список —
            # поэтому отсутствие scope user_brief незаметно превращало ФИО в
            # «Сотрудник #123». Ошибка должна быть видна в журнале/диагностике.
            if isinstance(data, dict) and data.get("error"):
                msg = data.get("error_description") or data.get("error")
                raise RuntimeError(f"Битрикс24 отклонил {method}: {msg}")
            result = data.get("result", [])
            if isinstance(result, dict):  # некоторые методы возвращают объект
                # crm.stagehistory.list кладёт строки во вложенный result.items,
                # но next/total оставляет во внешнем конверте как обычные crm.*.
                items = result.get("items")
                if isinstance(items, list):
                    out.extend(items)
                else:
                    out.append(result)
                    break
            else:
                out.extend(result)
            nxt = data.get("next")
            if not nxt:
                break
            start = nxt
    return out


def _rest(method: str, payload: dict, webhook_url: str | None = None) -> Any:
    """Одиночный REST-вызов с проверкой конверта ошибки.

    Битрикс24 отвечает HTTP 200 и при отказе (ошибка лежит в теле), поэтому без
    разбора конверта интерфейс показывал бы успех на несозданной задаче.
    """
    base = _base() if webhook_url is None else _base(webhook_url)
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = request(
            "POST", f"{base}/{method}.json", client=client, json=payload
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Битрикс24 вернул не-JSON на {method} (HTTP {resp.status_code})"
        ) from exc
    if isinstance(data, dict) and data.get("error"):
        msg = data.get("error_description") or data.get("error")
        raise RuntimeError(f"Битрикс24 отклонил {method}: {msg}")
    return data.get("result") if isinstance(data, dict) else None


def _user_id(value: Any) -> str:
    """ID сотрудника Битрикс24 или «» — если ответственный не назначен.

    У сделки без ответственного ASSIGNED_BY_ID приходит нулём, а «0» — непустая
    строка: она проходила проверку на заполненность и уезжала в RESPONSIBLE_ID,
    из-за чего задача создавалась со статусом «Не распределено».
    """
    text = str(value or "").strip()
    return "" if text in ("", "0") else text


def _coerce(value: Any) -> str:
    """Значение пользовательского поля Битрикс → строка (список → через запятую)."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(x) for x in value if x not in (None, ""))
    return str(value)


def normalize_deal(raw: dict, extra_fields: dict[str, str] | None = None) -> dict:
    """Провайдер-специфичные поля сделки → нормализованная запись для ingest.

    extra_fields — карта {семантический_ключ: код поля Битрикс} (сопоставление на
    странице «Интеграции»); их значения складываются в result["custom"].
    """
    deal_id = raw.get("ID") or raw.get("id")
    custom: dict[str, str] = {}
    for key, code in (extra_fields or {}).items():
        custom[key] = _coerce(raw.get(code))
    return {
        "external_id": str(deal_id) if deal_id is not None else None,
        "ref": f"Сделка #{deal_id}" if deal_id is not None else "",
        "name": raw.get("TITLE") or raw.get("NAME") or "Без названия",
        "stage": raw.get("STAGE_ID"),
        "funnel_id": str(raw.get("CATEGORY_ID") or "0"),
        # Семантика стадии Битрикс: P — в работе, S — успех, F — провал/отказ.
        "semantic": raw.get("STAGE_SEMANTIC_ID"),
        "mgr": raw.get("ASSIGNED_BY_ID"),  # id; резолв имени — на этапе настройки
        "contact_id": raw.get("CONTACT_ID"),  # для подтягивания телефона контакта
        "src": raw.get("SOURCE_ID"),
        "utm": raw.get("UTM_SOURCE"),
        "campaign": raw.get("UTM_CAMPAIGN"),
        "amount": int(float(raw.get("OPPORTUNITY") or 0)),
        "created": raw.get("DATE_CREATE"),
        "last_activity": raw.get("LAST_ACTIVITY_TIME") or raw.get("DATE_MODIFY"),
        "custom": custom,
    }


def normalize_stage_history(raw: dict) -> dict | None:
    """Строка ``crm.stagehistory.list`` → нейтральная запись синхронизации."""
    owner_id = raw.get("OWNER_ID") or raw.get("ownerId")
    stage_id = raw.get("STAGE_ID") or raw.get("stageId")
    changed_at = (
        raw.get("CREATED_TIME") or raw.get("createdTime")
        or raw.get("CREATED_DATE") or raw.get("createdDate")
    )
    if owner_id is None or not stage_id:
        return None
    external_id = raw.get("ID") or raw.get("id")
    if external_id is None:
        external_id = f"{owner_id}:{stage_id}:{changed_at or ''}"
    return {
        "external_id": str(external_id),
        "deal_external_id": str(owner_id),
        "stage_id": str(stage_id),
        "changed_at": changed_at,
    }


def _activity_kind(raw: dict) -> str | None:
    try:
        activity_type = int(raw.get("TYPE_ID") or raw.get("typeId") or 0)
    except (TypeError, ValueError):
        activity_type = 0
    provider = str(
        raw.get("PROVIDER_ID") or raw.get("providerId") or ""
    ).lower()
    if activity_type == 2 or "call" in provider:
        return "call"
    if activity_type == 1 or "meeting" in provider:
        return "meeting"
    return None


def _duration_seconds(start: Any, end: Any, raw_duration: Any = None) -> int:
    try:
        if raw_duration not in (None, ""):
            return max(0, int(float(raw_duration)))
    except (TypeError, ValueError):
        pass
    try:
        left = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        right = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return max(0, round((right - left).total_seconds()))
    except (TypeError, ValueError):
        return 0


def normalize_activity(raw: dict) -> dict | None:
    """Оставляет из CRM-активности только звонки и встречи."""
    activity_id = raw.get("ID") or raw.get("id")
    owner_id = raw.get("OWNER_ID") or raw.get("ownerId")
    kind = _activity_kind(raw)
    if activity_id is None or owner_id is None or kind is None:
        return None
    started = (
        raw.get("START_TIME") or raw.get("startTime")
        or raw.get("CREATED") or raw.get("created")
    )
    ended = raw.get("END_TIME") or raw.get("endTime")
    return {
        "external_id": str(activity_id),
        "deal_external_id": str(owner_id),
        "kind": kind,
        "subject": str(raw.get("SUBJECT") or raw.get("subject") or ""),
        "responsible_id": str(
            raw.get("RESPONSIBLE_ID") or raw.get("responsibleId") or ""
        ),
        "occurred_at": started,
        "ended_at": ended,
        "duration_sec": _duration_seconds(
            started, ended, raw.get("DURATION") or raw.get("duration")
        ),
        "completed": str(raw.get("COMPLETED") or raw.get("completed") or "").upper()
        in {"Y", "1", "TRUE"},
        "direction": str(raw.get("DIRECTION") or raw.get("direction") or ""),
        "provider_id": str(raw.get("PROVIDER_ID") or raw.get("providerId") or ""),
    }


class RealBitrix24Adapter:
    def __init__(self, webhook_url: str | None = None, source_key: str = "primary") -> None:
        self.webhook_url = webhook_url
        self.source_key = source_key

    def _call(self, method: str, params: dict | None = None) -> list[dict]:
        # Два аргумента сохраняют совместимость тестов, подменяющих модульную функцию.
        if self.webhook_url is None:
            return _call(method, params)
        return _call(method, params, self.webhook_url)

    def _rest(self, method: str, payload: dict) -> Any:
        if self.webhook_url is None:
            return _rest(method, payload)
        return _rest(method, payload, self.webhook_url)

    def _base(self) -> str:
        return _base(self.webhook_url)

    def fetch_deals(
        self, created_after: str | None = None, extra_fields: dict[str, str] | None = None,
        modified_after: str | None = None,
    ) -> list[dict]:
        """Сделки портала.

        created_after — окно по дате создания (полная выгрузка).
        modified_after — только изменённые с указанного момента: короткая выборка
        для частой синхронизации, чтобы не тянуть всё окно каждые несколько минут.
        """
        select = [
            "ID", "TITLE", "CATEGORY_ID", "STAGE_ID", "STAGE_SEMANTIC_ID", "ASSIGNED_BY_ID",
            "CONTACT_ID", "SOURCE_ID", "OPPORTUNITY", "DATE_CREATE", "DATE_MODIFY",
            "LAST_ACTIVITY_TIME", "UTM_SOURCE", "UTM_CAMPAIGN",
        ]
        # Добавляем сопоставленные пользовательские поля в выборку.
        select += [c for c in {v for v in (extra_fields or {}).values() if v} if c not in select]
        params: dict[str, Any] = {"select": select}
        # Ограничение периода резко сокращает объём выгрузки (иначе постранично
        # тянется вся история портала). Даты — в формате ISO 8601.
        if modified_after:
            params["filter"] = {">=DATE_MODIFY": modified_after}
            params["order"] = {"DATE_MODIFY": "DESC"}
        elif created_after:
            params["filter"] = {">=DATE_CREATE": created_after}
            params["order"] = {"DATE_CREATE": "DESC"}
        raw = self._call("crm.deal.list", params)
        rows = [normalize_deal(d, extra_fields) for d in raw]
        for row in rows:
            row["crm_source"] = self.source_key
        return rows

    def fetch_deal_fields(self) -> list[dict]:
        """Список полей сделки: [{"code","title"}] (вкл. пользовательские UF_CRM_*)."""
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = request(
                "POST", f"{self._base()}/crm.deal.fields.json", client=client, json={}
            )
        result = resp.json().get("result", {})
        out: list[dict] = []
        for code, meta in (result.items() if isinstance(result, dict) else []):
            title = (meta or {}).get("title") or (meta or {}).get("formLabel") or code
            out.append({"code": code, "title": str(title)})
        return out

    def fetch_stage_history(
        self, deal_ids: list[str] | None = None, changed_after: str | None = None
    ) -> list[dict]:
        """История стадий выбранных сделок, нормализованная для ingest."""
        ids = [str(item) for item in (deal_ids or []) if item]
        batches = [ids[i:i + _PAGE] for i in range(0, len(ids), _PAGE)] if ids else [[]]
        out: list[dict] = []
        for batch in batches:
            filters: dict[str, Any] = {}
            if batch:
                filters["@OWNER_ID"] = batch
            if changed_after:
                filters[">=CREATED_TIME"] = changed_after
            params: dict[str, Any] = {
                "entityTypeId": 2,
                "order": {"CREATED_TIME": "ASC"},
            }
            if filters:
                params["filter"] = filters
            for row in self._call("crm.stagehistory.list", params):
                normalized = normalize_stage_history(row)
                if normalized is not None:
                    out.append(normalized)
        return out

    def fetch_activities(
        self, deal_ids: list[str], modified_after: str | None = None
    ) -> list[dict]:
        """Звонки и встречи сделок через ``crm.activity.list``."""
        ids = [str(item) for item in deal_ids if item]
        out: list[dict] = []
        for i in range(0, len(ids), _PAGE):
            batch = ids[i:i + _PAGE]
            filters: dict[str, Any] = {"OWNER_TYPE_ID": 2, "@OWNER_ID": batch}
            if modified_after:
                filters[">=LAST_UPDATED"] = modified_after
            rows = self._call("crm.activity.list", {
                "filter": filters,
                "order": {"LAST_UPDATED": "ASC"},
                "select": [
                    "ID", "OWNER_ID", "TYPE_ID", "PROVIDER_ID", "PROVIDER_TYPE_ID",
                    "SUBJECT", "START_TIME", "END_TIME", "CREATED", "LAST_UPDATED",
                    "COMPLETED", "RESPONSIBLE_ID", "DIRECTION",
                ],
            })
            for row in rows:
                normalized = normalize_activity(row)
                if normalized is not None:
                    out.append(normalized)
        return out

    def fetch_users(self) -> list[dict]:
        """Справочник сотрудников портала: [{"id", "name"}] для резолва ID → ФИО."""
        raw = self._call("user.get", {})
        out: list[dict] = []
        for u in raw:
            uid = u.get("ID") or u.get("id")
            if uid is None:
                continue
            parts = [u.get("NAME"), u.get("LAST_NAME")]
            name = " ".join(str(p).strip() for p in parts if p).strip()
            out.append({"id": str(uid), "name": name or f"ID {uid}"})
        return out

    def fetch_funnels(self) -> list[dict]:
        """Актуальные воронки сделок из ``crm.category.list``.

        Метод возвращает объект ``result.categories``, а не обычный список,
        поэтому здесь используется одиночный REST-вызов вместо ``_call``.
        """
        result = self._rest("crm.category.list", {"entityTypeId": 2})
        categories = result.get("categories", []) if isinstance(result, dict) else []
        funnels: list[dict] = []
        for category in categories:
            if not isinstance(category, dict) or category.get("id") is None:
                continue
            funnel_id = str(category["id"])
            funnels.append({
                "id": funnel_id,
                "name": str(category.get("name") or f"Воронка {funnel_id}"),
                "is_default": str(category.get("isDefault") or "").upper() == "Y",
                "sort": int(category.get("sort") or 0),
            })
        return sorted(funnels, key=lambda item: (item["sort"], item["name"]))

    def fetch_stages(self) -> list[dict]:
        """Справочник стадий воронки: [{"id", "name"}] для резолва STAGE_ID → название.

        Фильтр по ENTITY_ID обязателен: crm.status.list отдаёт единым списком все
        справочники портала (стадии, источники, типы), и без фильтра STATUS_ID
        источника мог перекрыть одноимённый код стадии.
        """
        raw = self._call("crm.status.list", {})
        out: list[dict] = []
        for s in raw:
            sid = s.get("STATUS_ID")
            entity = str(s.get("ENTITY_ID") or "")
            # Стадии основной воронки — DEAL_STAGE, дополнительных — DEAL_STAGE_<id>.
            if sid and entity.startswith("DEAL_STAGE"):
                out.append({"id": str(sid), "name": s.get("NAME") or str(sid)})
        return out

    def fetch_sources(self) -> list[dict]:
        """Справочник источников: [{"id", "name"}] для резолва SOURCE_ID → название.

        Без него на дашборде источник сделки показывается служебным кодом портала
        («site», «CALL»), по которому фильтр не читается."""
        raw = self._call("crm.status.list", {})
        out: list[dict] = []
        for s in raw:
            sid = s.get("STATUS_ID")
            if sid and str(s.get("ENTITY_ID") or "") == "SOURCE":
                out.append({"id": str(sid), "name": s.get("NAME") or str(sid)})
        return out

    def fetch_deal_responsible(self, deal_id: str) -> str:
        """Текущий ответственный по сделке (ASSIGNED_BY_ID) прямо из портала.

        Сохранённое у нас значение может устареть — сделку могли переназначить
        после последнего пересчёта, а исполнителем задачи должен стать тот, кто
        отвечает за сделку сейчас.
        """
        result = self._rest("crm.deal.get", {"id": deal_id})
        if isinstance(result, dict):
            return _user_id(result.get("ASSIGNED_BY_ID"))
        return ""

    def fetch_user_name(self, user_id: str) -> str:
        """ФИО сотрудника по ID (для подтверждения в интерфейсе); «» — если не найден."""
        result = self._rest("user.get", {"ID": user_id})
        rows = result if isinstance(result, list) else []
        for u in rows:
            parts = [u.get("NAME"), u.get("LAST_NAME")]
            name = " ".join(str(x).strip() for x in parts if x).strip()
            if name:
                return name
        return ""

    def _resolve_responsible(self, deal_id: str, stored: Any) -> str:
        """ID исполнителя задачи — ответственный по сделке (портал важнее кэша)."""
        try:
            live = self.fetch_deal_responsible(deal_id)
        except Exception as exc:  # noqa: BLE001 — падать из-за справочника не нужно
            logger.warning("Битрикс24: не удалось прочитать ответственного по сделке: %s", exc)
            live = ""
        return live or _user_id(stored)

    def fetch_contact_phones(self, contact_ids: list[str]) -> dict[str, str]:
        """Телефоны контактов: {contact_id: phone}. Телефон хранится у контакта,
        не в сделке, поэтому подтягивается отдельно (иначе поле «Телефон» пустое)."""
        ids = [str(c) for c in contact_ids if c]
        if not ids:
            return {}
        phones: dict[str, str] = {}
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            for i in range(0, len(ids), 50):  # выборками, оператор @ID = IN
                batch = ids[i:i + 50]
                start = 0
                while True:
                    resp = request(
                        "POST", f"{self._base()}/crm.contact.list.json", client=client,
                        json={"filter": {"@ID": batch}, "select": ["ID", "PHONE"], "start": start},
                    )
                    data = resp.json()
                    for c in data.get("result", []):
                        phone_list = c.get("PHONE") or []
                        value = phone_list[0].get("VALUE") if phone_list else None
                        if value:
                            phones[str(c.get("ID"))] = value
                    nxt = data.get("next")
                    if not nxt:
                        break
                    start = nxt
        return phones

    def fetch_tasks(self) -> list[dict]:
        return self._call("tasks.task.list", {})

    def fetch_open_action_deal_ids(self, deal_ids: list[str]) -> set[str]:
        """external_id сделок, у которых есть открытая задача или дело в Битрикс24.

        «Следующее действие» по сделке в Битриксе бывает двух видов, и правило
        «Сделка без задачи» должно гаснуть при любом из них:
        - дело/активность таймлайна (crm.activity.list, ownerTypeId=2) — то, что
          менеджер видит во вкладке «Дела», включая todo, созданные приложением;
        - задача модуля «Задачи», привязанная к сделке через UF_CRM_TASK=D_<id>.
        Оба источника best-effort: недоступность одного не роняет синхронизацию —
        просто признак остаётся неполным (в худшем случае лишнее «без задачи»,
        а не потерянная сделка).
        """
        wanted = {str(d) for d in deal_ids if d}
        if not wanted:
            return set()
        found: set[str] = set()

        # 1. Открытые дела/активности сделок (батчами по 50 id, оператор @ = IN).
        try:
            ids = sorted(wanted)
            for i in range(0, len(ids), 50):
                batch = ids[i:i + 50]
                rows = self._call("crm.activity.list", {
                    "filter": {"OWNER_TYPE_ID": 2, "COMPLETED": "N", "@OWNER_ID": batch},
                    "select": ["ID", "OWNER_ID"],
                })
                for r in rows:
                    owner = str(r.get("OWNER_ID") or "")
                    if owner in wanted:
                        found.add(owner)
        except Exception as exc:  # noqa: BLE001 — дела необязательны для синхронизации
            logger.warning("Битрикс24: список дел (активностей) недоступен: %s", exc)

        # 2. Открытые задачи, привязанные к сделкам (UF_CRM_TASK = D_<id>).
        try:
            for task in self._open_tasks():
                binding = task.get("ufCrmTask") or task.get("UF_CRM_TASK") or []
                if isinstance(binding, str):
                    binding = [binding]
                for b in binding:
                    text = str(b)
                    if text.startswith("D_") and text[2:] in wanted:
                        found.add(text[2:])
        except Exception as exc:  # noqa: BLE001 — задачи необязательны для синхронизации
            logger.warning("Битрикс24: список задач недоступен: %s", exc)

        return found

    def _open_tasks(self) -> list[dict]:
        """Незавершённые задачи портала с CRM-привязкой (постранично).

        tasks.task.list отдаёт иной конверт, чем crm.*-методы (список лежит в
        result.tasks), поэтому обходим страницы отдельно, а не через _call.
        """
        out: list[dict] = []
        start = 0
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            while True:
                resp = request("POST", f"{self._base()}/tasks.task.list.json", client=client, json={
                    "filter": {"!STATUS": 5}, "select": ["ID", "UF_CRM_TASK"], "start": start,
                })
                data = resp.json()
                result = data.get("result") or {}
                tasks = result.get("tasks") if isinstance(result, dict) else None
                if tasks:
                    out.extend(tasks)
                nxt = data.get("next")
                if not nxt:
                    break
                start = nxt
        return out

    def create_task(self, payload: dict) -> dict:
        """Ставит задачу ответственному и заводит «Дело» в карточке сделки.

        Задача (tasks.task.add) живёт в разделе «Задачи» и привязывается к сделке
        через UF_CRM_TASK. Но в карточке сделки менеджер смотрит на таймлайн
        «Дела», где задача сама по себе не появляется, — поэтому дополнительно
        создаём CRM-дело (crm.activity.todo.add) с тем же сроком и текстом.
        """
        deal_id = payload.get("deal_external_id")
        if not deal_id:
            raise RuntimeError(
                "У сделки не сохранён идентификатор Битрикс24 — задачу некуда "
                "привязать. Выполните пересчёт на странице «Интеграции»."
            )
        # Исполнитель задачи — ответственный по сделке. RESPONSIBLE_ID обязателен
        # для tasks.task.add: без него (или с нулём) задача выходит «Не распределено».
        responsible = self._resolve_responsible(deal_id, payload.get("assignee_id"))
        if not responsible:
            raise RuntimeError(
                "У сделки в Битрикс24 не назначен ответственный — некому поставить "
                "задачу. Назначьте ответственного по сделке и повторите."
            )

        title = payload.get("title", "Задача по сделке")
        deal_ref = payload.get("deal_ref")
        description = f"Сделка: {deal_ref}" if deal_ref else ""
        due_at = payload.get("due_at")
        deadline = due_at.isoformat() if hasattr(due_at, "isoformat") else None

        fields: dict[str, Any] = {
            "TITLE": title,
            "RESPONSIBLE_ID": responsible,
            # Привязка к сделке — задача видна в карточке сделки, вкладка «Задачи».
            "UF_CRM_TASK": [f"D_{deal_id}"],
        }
        if description:
            fields["DESCRIPTION"] = description
        if deadline:
            fields["DEADLINE"] = deadline

        result = self._rest("tasks.task.add", {"fields": fields})
        task = result.get("task", {}) if isinstance(result, dict) else {}
        task_id = task.get("id")
        if not task_id:
            raise RuntimeError("Битрикс24 не вернул идентификатор созданной задачи.")

        activity_id = self._add_deal_activity(
            deal_id=deal_id, responsible=responsible, title=title,
            description=description, deadline=deadline,
        )
        # Имя исполнителя — чтобы интерфейс подтверждал того, кому задача ушла
        # в портале, а не того, кто числился ответственным на момент выгрузки.
        try:
            assignee = self.fetch_user_name(responsible)
        except Exception as exc:  # noqa: BLE001 — задача уже создана, имя не критично
            logger.warning("Битрикс24: имя исполнителя недоступно: %s", exc)
            assignee = ""
        return {
            "ok": True, "external_id": task_id, "activity_id": activity_id,
            "assignee_id": responsible, "assignee": assignee, "mock": False,
        }

    def _add_deal_activity(
        self, *, deal_id: str, responsible: str, title: str,
        description: str, deadline: str | None,
    ) -> str | None:
        """Создаёт «Дело» в таймлайне сделки (ownerTypeId=2 — сделка)."""
        params: dict[str, Any] = {
            "ownerTypeId": 2,
            "ownerId": deal_id,
            "title": title,
            "responsibleId": responsible,
        }
        if description:
            params["description"] = description
        if deadline:
            params["deadline"] = deadline
        result = self._rest("crm.activity.todo.add", params)
        if isinstance(result, dict):
            return str(result.get("id") or "") or None
        return str(result) if result else None
