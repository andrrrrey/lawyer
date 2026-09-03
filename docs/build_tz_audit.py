from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


OUT = Path(__file__).with_name("Отчёт-по-соответствию-ТЗ-Lawyer.docx")
BLUE = "315E86"
DARK = "1F2937"
MUTED = "667085"
LINE = "D0D5DD"
LIGHT = "F2F4F7"
GREEN = "E7F6EC"
YELLOW = "FFF4CC"
RED = "FDECEC"
PURPLE = "F1ECFF"


def shade(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for key, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{key}"))
        if node is None:
            node = OxmlElement(f"w:{key}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_cell_width(cell, width: int) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width))
    tc_w.set(qn("w:type"), "dxa")


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_row_cant_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:cantSplit")) is None:
        tr_pr.append(OxmlElement("w:cantSplit"))


def set_table_fixed(table) -> None:
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")


def set_cell_border(cell, color=LINE, size="4") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = qn(f"w:{edge}")
        node = borders.find(tag)
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), size)
        node.set(qn("w:color"), color)


def set_run(run, *, size=None, bold=None, color=None, name="Calibri") -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def add_page_field(paragraph) -> None:
    run = paragraph.add_run()
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.extend((fld_char1, instr, fld_char2))
    set_run(run, size=8.5, color=MUTED)


def status_fill(status: str) -> str:
    if status == "Реализовано":
        return GREEN
    if status in {"Частично", "Требует настройки"}:
        return YELLOW
    if status == "Отложено":
        return PURPLE
    return RED


def add_para(doc, text: str = "", *, style=None, bold_lead: str | None = None):
    p = doc.add_paragraph(style=style)
    if bold_lead and text.startswith(bold_lead):
        r = p.add_run(bold_lead)
        set_run(r, bold=True)
        r = p.add_run(text[len(bold_lead):])
        set_run(r)
    else:
        r = p.add_run(text)
        set_run(r)
    return p


def add_bullet(doc, text: str, level: int = 0):
    style = "List Bullet" if level == 0 else "List Bullet 2"
    return add_para(doc, text, style=style)


def add_number(doc, text: str):
    return add_para(doc, text, style="List Number")


def add_callout(doc, title: str, text: str, fill=LIGHT, trailing=True) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_fixed(table)
    cell = table.cell(0, 0)
    set_cell_width(cell, 9360)
    set_cell_margins(cell, 130, 180, 130, 180)
    set_cell_border(cell, color=fill, size="1")
    shade(cell, fill)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(title)
    set_run(r, bold=True, color=BLUE, size=10.5)
    p = cell.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run(text)
    set_run(r, size=9.5, color=DARK)
    if trailing:
        doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_matrix(doc, rows):
    table = doc.add_table(rows=1, cols=4)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_fixed(table)
    widths = (1950, 1320, 4650, 1440)
    headers = ("Требование ТЗ", "Статус", "Как реализовано / где находится", "Что осталось")
    hdr = table.rows[0]
    set_repeat_table_header(hdr)
    for idx, cell in enumerate(hdr.cells):
        set_cell_width(cell, widths[idx])
        set_cell_margins(cell)
        set_cell_border(cell)
        shade(cell, LIGHT)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(headers[idx])
        set_run(r, size=8.3, bold=True, color=DARK)
    for req, status, impl, remain in rows:
        row = table.add_row()
        set_row_cant_split(row)
        cells = row.cells
        values = (req, status, impl, remain)
        for idx, cell in enumerate(cells):
            set_cell_width(cell, widths[idx])
            set_cell_margins(cell)
            set_cell_border(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            if idx == 1:
                shade(cell, status_fill(status))
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(values[idx])
            set_run(r, size=8.2, bold=(idx in (0, 1)), color=DARK)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_two_col(doc, rows, widths=(2600, 6760)):
    table = doc.add_table(rows=0, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_fixed(table)
    for label, value in rows:
        cells = table.add_row().cells
        for idx, cell in enumerate(cells):
            set_cell_width(cell, widths[idx])
            set_cell_margins(cell)
            set_cell_border(cell)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(label if idx == 0 else value)
            set_run(r, size=9, bold=(idx == 0), color=BLUE if idx == 0 else DARK)
        shade(cells[0], LIGHT)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def build() -> None:
    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Inches(8.5)
    sec.page_height = Inches(11)
    sec.top_margin = Inches(1)
    sec.bottom_margin = Inches(1)
    sec.left_margin = Inches(1)
    sec.right_margin = Inches(1)
    sec.header_distance = Inches(0.492)
    sec.footer_distance = Inches(0.492)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    normal.font.size = Pt(11)
    normal.font.color.rgb = RGBColor.from_string(DARK)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.1
    for name in ("List Bullet", "List Bullet 2", "List Number"):
        st = doc.styles[name]
        st.font.name = "Calibri"
        st._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
        st.font.size = Pt(10.5)
        st.paragraph_format.space_after = Pt(4)
    for name, size, before, after in (("Title", 24, 0, 12), ("Heading 1", 16, 16, 8), ("Heading 2", 13, 12, 6), ("Heading 3", 12, 8, 4)):
        st = doc.styles[name]
        st.font.name = "Calibri"
        st._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
        st.font.size = Pt(size)
        st.font.bold = True
        st.font.color.rgb = RGBColor.from_string(BLUE if name != "Title" else DARK)
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)
        st.paragraph_format.keep_with_next = True

    header = sec.header
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = hp.add_run("LAWYER  /  АУДИТ ТЕХНИЧЕСКОГО ЗАДАНИЯ")
    set_run(r, size=8.5, bold=True, color=MUTED)
    footer = sec.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = fp.add_run("Конфиденциально  ·  03.09.2026  ·  ")
    set_run(r, size=8.5, color=MUTED)
    add_page_field(fp)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run("ОТЧЁТ О СООТВЕТСТВИИ ТЗ")
    set_run(r, size=10, bold=True, color=BLUE)
    p = doc.add_paragraph(style="Title")
    r = p.add_run("Lawyer")
    set_run(r, size=24, bold=True, color=DARK)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(18)
    r = p.add_run("Управленческая панель продаж и маркетинга")
    set_run(r, size=16, color=MUTED)
    add_two_col(doc, [
        ("Основание", "«ТЗ — панель продаж — итоговое — Lawyer»"),
        ("Объект проверки", "Исходный код, база данных и production lawyer.futuguru.com"),
        ("Дата среза", "3 сентября 2026 года"),
        ("Назначение", "Сверка требований, текущей реализации и остаточных работ"),
    ])
    add_callout(doc, "Главный вывод", "Система развёрнута и имеет рабочую базу для двух Bitrix24, трёх юрлиц, 1С, Яндекса, SLA, расходов и ROMI. Однако полное соответствие ТЗ пока не достигнуто: часть боевых источников не даёт фактов, а ряд аналитических и ролевых функций ещё не реализован.", fill=YELLOW)

    doc.add_heading("1. Как читать отчёт", level=1)
    add_two_col(doc, [
        ("Реализовано", "Функция есть в коде, видна в интерфейсе или работает в сервисном слое."),
        ("Частично", "Есть каркас или часть расчёта, но не все поля, формулы или источники доведены до результата."),
        ("Требует настройки", "Код готов, но нужны доступы, сопоставления или начальные данны Заказчика."),
        ("Не реализовано", "Требуется доработка кода."),
        ("Отложено", "Исключено из текущего запуска по прямому указанию Заказчика."),
    ])

    doc.add_heading("2. Итог аудита", level=1)
    add_para(doc, "Проверка выполнена по актуальному ТЗ, коду, миграциям, API, production-базе и собранному web-интерфейсу. Доступы и секреты в отчёт не включены.")
    add_bullet(doc, "Платформа развёрнута на https://lawyer.futuguru.com, API в production отвечает, PostgreSQL и миграции актуальны.")
    add_bullet(doc, "В базе 354 сделки Bitrix24, но 0 записей истории стадий, 0 поступлений 1С, 0 расходов Директа, 0 визитов Метрики и 0 AI-инсайтов. Это ограничивает полезность части блоков.")
    add_bullet(doc, "Включено 15 воронок вместо 11 из ТЗ; это не ошибка механизма, но незавершённая бизнес-настройка.")
    add_bullet(doc, "Отделы, сотрудники и планы в production не заполнены; список менеджеров зависит от прав Bitrix24 на метод user.get.")
    add_bullet(doc, "Ручные расходы и возвращённый ROMI внесены в production; миграция 0009 применена, 114 backend-тестов прошли.")

    doc.add_heading("3. Источники данных и архитектура", level=1)
    add_matrix(doc, [
        ("Один дашборд; 3 юрлица", "Реализовано", "Единое приложение. Глобальный фильтр юрлица; Настройки → Юрлица. ИНН ЮО, ЦСВ и УрПАСЭ заданы.", "Ничего по трём основным юрлицам."),
        ("2 портала Bitrix24", "Частично", "Интеграции → Bitrix24: два входящих webhook. Сделки загружаются; есть проверка связи и выбор воронок.", "Выгрузка истории стадий и активностей не включена в конвейер."),
        ("Имена ответственных", "Требует настройки", "Настройки → Структура и планы: сопоставление ID пользователя, источника CRM, ФИО, юрлица и отдела.", "Дать webhook право user_brief/user.get или заполнить сопоставления вручную."),
        ("1С: POST + Basic", "Требует настройки", "Адаптер боевого endpoint, Basic Authentication, скользящее окно, дедупликация и журнал сопоставлений реализованы.", "В production 0 поступлений: проверить учётные данны, сеть и ручной запуск ingest."),
        ("Фильтры поступлений 1С", "Реализовано", "ИНН получателя; Код_BTX/Тип_BTX; исключение внутригрупповых переводов; белый список точных статей ДДС; типы операций.", "Тест на боевой выгрузке и разбор исключённых/несопоставленных строк."),
        ("РЦА", "Отложено", "Не включено в три утверждённых юрлица.", "Нужен точный ИНН и решение о включении."),
        ("3 аккаунта Директа/Метрики", "Требует настройки", "Интеграции → Яндекс: отдельные поля на ЮО, ЦСВ, УрПАСЭ; адаптеры Direct Reports API и Metrika API.", "Токены есть, но нужны логины Direct и ID счётчиков; в базе пока 0 расходов/0 визитов."),
    ])

    doc.add_heading("4. Воронка, планирование и менеджеры", level=1)
    add_matrix(doc, [
        ("11 воронок", "Требует настройки", "Настройки → Воронки: система читает их из обоих Bitrix24, позволяет выбрать нужные, привязать юрлицо и SLA.", "Сейчас включено 15. Оставить точно 7 ЮО + 2 УрПАСЭ + 2 lead-воронки."),
        ("Этапы и конверсии", "Частично", "На дашборде есть «Воронка обработки» с конверсиями и периодом.", "Нет глобального фильтра воронки; расчёт не опирается на фактическую историю стадий."),
        ("Планы по месяцам", "Частично", "Настройки → Структура и планы: ввод выручки, оплат и сделок по сотруднику/юрлицу/месяцу.", "Добавить звонки и встречи; план компании/отдела; план-факт и % выполнения. В production планов 0."),
        ("Ожидание оплат", "Не реализовано", "В настройках можно указать целевые стадии воронок.", "Нужны формулы ожидания по типам воронок и финальное правило «Заключение Контракта»."),
        ("Средние суммы", "Не реализовано", "Базовые суммы Bitrix24 и 1С хранятся раздельно.", "Добавить KPI «Средняя сумма договора» и «Средняя сумма поступления»."),
        ("Цикл сделки", "Не реализовано", "Даты создания/закрытия частично доступны в сырье.", "Нужны метрика, разрезы и визуализация."),
        ("Карточки менеджеров", "Частично", "Дашборд → «Контроль менеджеров»: в работе, просрочки, без задачи, счета, оплаты, сумма, зона.", "Добавить личную конверсию, план/факт продаж, звонков, встреч."),
        ("Агрегаты отделов/МОП", "Не реализовано", "Справочники отделов и привязки сотрудников есть в настройках.", "Нужен отдельный расчёт/блок: лиды, сделки в работе, конверсии, звонки."),
    ])

    doc.add_heading("5. Контроль, SLA и AI", level=1)
    add_matrix(doc, [
        ("Сделки без движения", "Частично", "Мониторинг и настраиваемые пороги реализованы; SLA вынесен в настройки с историей/откатом.", "Загружать stage_history и фактическое время входа в стадию; сейчас в базе 0 переходов."),
        ("Без повторного касания", "Частично", "Правило и порог 10 дней предусмотрены движком мониторинга.", "Импортировать звонки/встречи и исключения по договорённости с клиентом."),
        ("Отказы Спам/Дубль", "Частично", "Причина отказа может храниться в custom-полях; оценочные нарушения вынесены в настройки.", "Уточнить поле Bitrix24 и механизм ручной проверки."),
        ("SLA 1–6", "Частично", "Профиль SLA из файла вынесен в Настройки → SLA; пороги, задачи, поля, график, дубли и история изменений есть.", "Автопроверки 1, 5, 6 не надёжны без первого касания и истории активностей; п. 2/4 требуют формализации."),
        ("Задача из алерта", "Реализовано", "В мониторинге есть действие создания задачи через Bitrix24.", "Боевая приёмка прав webhook на crm.task.add."),
        ("Еженедельный AI-разбор", "Требует настройки", "Планировщик на понедельник 03:30 и хранилище AI-инсайтов реализованы.", "Нужен ключ LLM и боевые данны; сейчас AI-инсайтов 0."),
        ("AI-комментарий по сделке", "Не реализовано", "Поле для комментария в модели сделки есть.", "Нужен построчный конвейер, промпт, лимиты/повторы и отображение."),
    ])

    doc.add_heading("6. Маркетинг, расходы и ROMI", level=1)
    add_callout(doc, "Решение по вопросу о ROMI", "Блок «ROMI по каналам» нужен по п. 3.6 ТЗ и возвращён на дашборд. Он не показывает демо-цифры: до появления расходов и привязанных поступлений 1С выводит честное пустое состояние.", fill=GREEN)
    add_matrix(doc, [
        ("Источники лидов", "Реализовано", "Дашборд → «Источники лидов»; разбивка по полю источника Bitrix24, фильтр источника.", "Проверить таксономию и UTM на боевых данных."),
        ("Расходы Директа", "Требует настройки", "Посуточная загрузка Direct Reports API, приведение к базе без НДС, разрез по юрлицу/периоду/кампании.", "Заполнить логины аккаунтов, проверить права и запустить выгрузку."),
        ("Ручные статьи расходов", "Реализовано", "Новое требование: Настройки → Расходы. Дата, юрлицо, статья, сумма, канал, кампания, комментарий; журнал и удаление.", "Заполняется пользователем."),
        ("Блок расходов", "Реализовано", "Дашборд → «Расходы по статьям»: сумма автоматического Директа и всех ручных статей; фильтр периода/юрлица.", "Появится после первой записи или выгрузки Директа."),
        ("ROMI по каналам", "Реализовано", "Дашборд и раздел ROMI. Формула: (база дохода − рекламный расход) / расход × 100%. В ROMI входят Direct и только ручные строки с флагом.", "Нужны факты Direct и связанные поступления 1С; иначе блок пуст. Не дублировать Direct вручную."),
        ("Маржа в ROMI", "Частично", "Выручка берётся только из разрешённых фактических поступлений 1С, не из успешной стадии Bitrix24.", "Источника себестоимости нет. До его появления это ROMI по выручке, а не по бухгалтерской марже."),
    ])

    doc.add_heading("7. Доступ и эксплуатация", level=1)
    add_matrix(doc, [
        ("Веб-панель", "Реализовано", "HTTPS, авторизация, закрытый API, Docker Compose, healthcheck, миграции, worker, backup-скрипты.", "Настроить операционный контроль бэкапов и алертов."),
        ("Роли: собственник/руководитель/менеджер", "Не реализовано", "Сейчас одна учётная запись администратора без RBAC.", "Добавить пользователей, роли и скрытие финансов для менеджера."),
        ("Telegram-бот", "Отложено", "Не подключён по последнему указанию Заказчика.", "Вернуть в объём после отдельного решения."),
        ("Calltouch", "Отложено", "Скрыт из интерфейса по решению Заказчика.", "Не включать в текущую приёмку."),
    ])

    doc.add_heading("8. Приоритетный план доведения", level=1)
    doc.add_heading("P0 — данные и бизнес-настройки", level=2)
    for text in (
        "Оставить в панели ровно 11 воронок и привязать каждую к юрлицу и SLA; подтвердить «Заключение Контракта».",
        "Добавить в webhook Bitrix24 права на чтение пользователей/активностей; заполнить сотрудников и отделы.",
        "Проверить боевую выгрузку 1С и разобрать журнал исключений/несопоставленных поступлений.",
        "Заполнить Direct-логины и ID счётчиков для трёх юрлиц; запустить и сверить загрузку.",
        "Внести начальные планы после доработки модели план-факта.",
    ):
        add_number(doc, text)
    doc.add_heading("P1 — недостающая логика ТЗ", level=2)
    for text in (
        "Выгружать историю стадий, звонки и встречи; заполнять first_contact_at/stage_entered_at и SLA-факты.",
        "Добавить в общую панель фильтр воронки и пересчёт конверсий по истории.",
        "Завершить план-факт компании/отдела/сотрудника по продажам, звонкам и встречам.",
        "Реализовать ожидаемые оплаты, две средние суммы, цикл сделки, менеджерские и отдельские KPI.",
        "Добавить RBAC и скрытие финансов для роли менеджера; построчные AI-комментарии.",
    ):
        add_number(doc, text)

    doc.add_heading("9. Приёмка нового блока расходов", level=1)
    for text in (
        "В «Настройки → Расходы» создаётся запись с датой, юрлицом, статьёй и положительной суммой.",
        "Строка удаляется из журнала только после подтверждения.",
        "Общий расход виден в «Расходах по статьям» за выбранные период и юрлицо.",
        "В ROMI попадает только ручная строка с флагом «Учитывать в ROMI»; для неё канал обязателен.",
        "Загруженный расход Директа появляется автоматически как отдельная статья; он не вводится вручную.",
        "При отсутствии расходов или связанной выручки ROMI не выдумывает число, а показывает пустое состояние.",
    ):
        add_bullet(doc, text)

    doc.add_heading("10. Техническая карта", level=1)
    add_two_col(doc, [
        ("Дашборд", "frontend/src/pages/DashboardPage.tsx"),
        ("Журнал расходов", "frontend/src/pages/BusinessSettingsPage.tsx → вкладка «Расходы»"),
        ("API расходов", "GET/POST /api/admin/expenses; PUT/DELETE /api/admin/expenses/{id}"),
        ("Агрегация статей", "GET /api/dashboard/expenses-by-article"),
        ("ROMI", "GET /api/romi/by-channel; backend/app/services/analytics.py; channels.py; metrics.py"),
        ("Модель БД", "manual_expenses; Alembic 0009_manual_expenses.py"),
        ("Настройки бизнеса", "GET/PUT /api/admin/business-settings"),
        ("Интеграции", "GET/PUT /api/integrations/settings; /test/*; /bitrix/funnels"),
        ("Документация", "docs/ADMIN.md, DB_SCHEMA.md, ROMI_METHODOLOGY.md, ACCEPTANCE_CHECKLIST.md"),
    ])
    add_callout(doc, "Граница вывода", "Отчёт отражает состояние кода и production на 03.09.2026. Пункты со статусом «Требует настройки» не считаются принятыми до появления боевых фактов; «Частично» и «Не реализовано» требуют доработки до финальной приёмки.", fill=LIGHT, trailing=False)

    core = doc.core_properties
    core.title = "Lawyer — отчёт о соответствии ТЗ"
    core.subject = "Сверка ТЗ, production и исходного кода"
    core.author = "Lawyer"
    core.keywords = "Lawyer, ТЗ, аудит, Bitrix24, 1С, ROMI"
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()
