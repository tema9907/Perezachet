"""
Генерация итогового docx «Экспертное заключение».
Использует discipline_db для автозаполнения кредитов и расчёта соответствия.
Структура таблицы повторяет колонки из примера (без сложного форматирования):

  №, ФИО, ОП, Курс,
  По плану: Дисциплина, Кредиты,
  Фактически: Курсы (название + источник + часы), Кредиты/часы, Баллы,
  Заключение: Соответствие, Примечание,
  Зачтённая оценка
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

try:
    import discipline_db as _ddb
except ImportError:
    _ddb = None  # type: ignore

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt


# ---------------------------------------------------------------------------
# Public payload schema
# ---------------------------------------------------------------------------
@dataclass
class CourseEntry:
    course_title: str = ""
    provider: str = ""
    hours: str = ""
    grade: str = ""
    date: str = ""

    @property
    def clean_hours(self) -> str:
        if not self.hours.strip():
            return ""
        m = re.search(r"(\d+(?:[.,]\d+)?)", self.hours)
        if m:
            try:
                val = float(m.group(1).replace(",", "."))
                return f"{int(val)} ч" if val.is_integer() else f"{val} ч"
            except ValueError:
                pass
        return self.hours.strip()

    def format(self) -> str:
        """«Название курса (Провайдер, часы)» — вместо даты выводим часы."""
        head = self.course_title.strip()
        meta_bits = [b for b in (self.provider.strip(), self.clean_hours) if b]
        if meta_bits:
            head = f"{head} ({', '.join(meta_bits)})" if head else f"({', '.join(meta_bits)})"
        return head


@dataclass
class DisciplineRow:
    discipline: str = ""
    plan_credits: str = ""
    courses: list[CourseEntry] = field(default_factory=list)
    total_hours: str = ""
    grade_points: str = ""
    compliance: str = "полное"
    note: str = ""
    final_grade: str = ""


@dataclass
class ReportPayload:
    student_name: str = ""
    program_code: str = ""
    course_year: str = ""
    rows: list[DisciplineRow] = field(default_factory=list)
    experts: list[str] = field(default_factory=lambda: [
        "Борамбаева Г.М., ст.преподаватель кафедры ИКТ",
        "Жекеева С.С., ст.преподаватель кафедры ИКТ",
        "Никишина О.А., ст.преподаватель кафедры ИКТ",
    ])


# ---------------------------------------------------------------------------
# Helpers: derive program name from group code (e.g. АПО-23 -> Архитектор ПО)
# ---------------------------------------------------------------------------
PROGRAM_MAP: dict[str, str] = {
    "А": "7M08101 «Агрономия»",
    "АJ": "7M08101 «Агрономия»",
    "АГРО": "6B08101 «Агрономия»",
    "АМДИ": "6B05308 «Астрономия и методы дистанционных исследований (US)»",
    "АПО": "6B06105 «Архитектор программного обеспечения»",
    "Б": "6B01513 «Биология (IP)»",
    "БJ": "7M05101 «Биология»",
    "БМ": "6B04108 «Бизнес и менеджмент»",
    "БТ": "6B05103 «Биотехнология (US)»",
    "ВТИПО": "6B06104 «Вычислительная техника и программное обеспечение»",
    "Г": "6B01518 «География (IP)»",
    "ГJ": "7M05201 «География»",
    "ГИП": "6B05203 «География и природопользование»",
    "ДА": "7M04102 «Деловое администрирование(MBA)»",
    "ДЗ": "6B02101 «Дизайн»",
    "ДОВ": "6B01201 «Дошкольное обучение и воспитание»",
    "Ж": "7M03201 «Журналистика»",
    "ЖJ": "7M03201 «Журналистика»",
    "И": "7M02201 «История»",
    "ИВТУ": "8D06101 «Информатика, вычислительная техника и управление»",
    "ИВТУI": "8D06102 «Информатика, вычислительная техника и управление»",
    "ИВТУJ": "8D06101 «Информатика, вычислительная техника и управление»",
    "ИИИТ": "6B07504 «Инжиниринг и инновационно-измерительные технологии»",
    "ИН": "6B01517 «Информатика (IP)»",
    "ИО": "6B01602 «История и обществознание (IP)»",
    "ИС": "7M06102 «Информационные системы»",
    "ИС": "6B06102 «Информационные системы»",
    "ИСJ": "7M06102 «Информационные системы»",
    "ИСУ": "6B06106 «Информационные системы в управлении»",
    "ИФ": "6B02302 «Иностранная филология»",
    "ИЯ": "7M01701 «Иностранный язык: два иностранных языка»",
    "ИЯJ": "7M01701 «Иностранный язык: два иностранных языка»",
    "КДР": "6B11101 «Культурно-досуговая работа»",
    "КЯЛ": "6B01706 «Казахский язык и литература (IP)»",
    "КЯЛJ": "7M01705 «Казахский язык и литература»",
    "ЛРЛ": "6B08301 «Лесные ресурсы и лесоводство»",
    "М": "6B01516 «Математика (IP)»",
    "МЕ": "7M04104 «Менеджмент»",
    "МЕJ": "7M04104 «Менеджмент»",
    "МЕД": "6B10104 «Медицина»",
    "МИ": "6B01508 «Математика-Информатика»",
    "МО": "6B01406 «Музыкальное образование (IP)»",
    "МС": "8D07101 «Машиностроение»",
    "МСI": "8D07106 «Машиностроение»",
    "МСJ": "7M07101 «Машиностроение»",
    "МСJI": "8D07106 «Машиностроение»",
    "МФ": "6B01509 «Математика-Физика»",
    "НО": "6B01303 «Начальное образование (IP)»",
    "НОИП": "6B01302 «Начальное образование и инклюзивная практика (US)»",
    "НРТ": "6B08104 «Наука о растениях и технологии (US)»",
    "ОМ": "6B10101 «Общая медицина»",
    "ПВО": "6B01103 «Психология в образовании»",
    "ПД": "6B02303 «Переводческое дело»",
    "ПИМСО": "6B07302 «Проектирование и информационное моделирование строительных объектов»",
    "ПМНО": "6B01301 «Педагогика и методика начального обучения»",
    "ППС": "7M01101 «Педагогика и психология»",
    "ППСJ": "7M01101 «Педагогика и психология»",
    "РИС": "6B07109 «Робототехнические и интеллектуальные системы»",
    "РИСП": "7M07106 «Робототехнические, интеллектуальные системы и приборостроение»",
    "РИСПJ": "7M07106 «Робототехнические, интеллектуальные системы и приборостроение»",
    "РИТМ": "6B07108 «Робототехника и инновационные технологии в машиностроении»",
    "РЛ": "6B01705 «Русский язык и литература в школах с русским и нерусским языками обучения (IP)»",
    "РЭТ": "8D06201 «Радиотехника, электроника и телекоммуникации»",
    "С": "6B07301 «Строительство»",
    "СОЦП": "6B01802 «Социальная педагогика»",
    "СП": "6B01908 «Специальная педагогика (IP)»",
    "СПJ": "7M01903 «Специальная педагогика»",
    "СПИП": "6B01907 «Специальная педагогика и инклюзивная практика (US)»",
    "ССI": "7M07504 «Стандартизация и сертификация (по отраслям)»",
    "ССМ": "7M07502 «Стандартизация, сертификация и метрология (по отраслям)»",
    "ССМJ": "7M07502 «Стандартизация, сертификация и метрология (по отраслям)»",
    "Т": "6B11102 «Туризм»",
    "ТПП": "6B07201 «Технология продовольственных продуктов»",
    "ТППЖ": "7M08201 «Технология производства продуктов животноводства»",
    "ТР": "8D07105 «Транспорт, транспортная техника и технологии»",
    "ТРJ": "8D07105 «Транспорт, транспортная техника и технологии»",
    "ТЭОРВ": "6B07107 «Техническая эксплуатация, обслуживание и ремонт вагонов»",
    "УИА": "6B04105 «Учет и аудит»",
    "Ф": "6B01515 «Физика (IP)»",
    "ФА": "7M04108 «Финансовая аналитика»",
    "ФАРМ": "6B10102 «Фармация»",
    "ФИ": "6B01510 «Физика-Информатика»",
    "ФИЛ": "7M02301 «Филология»",
    "ФКНВП": "6B01404 «Физическая культура и начальная военная подготовка»",
    "ФКС": "6B01405 «Физическая культура и спорт (IP)»",
    "ФС": "6B04104 «Финансы»",
    "Х": "6B01519 «Химия (IP)»",
    "ХJ": "7M01504 «Химия»",
    "ХБ": "6B01511 «Химия-Биология»",
    "ХТОВ": "8D07102 «Химическая технология органических веществ»",
    "ХТОВI": "8D07107 «Химическая технология органических веществ»",
    "ХЭАКП": "6B05307 «Химическая экспертиза и аналитический контроль производства (US)»",
    "Э": "8D04101 «Экономика»",
    "ЭJ": "8D04101 «Экономика»",
    "ЭИТ": "6B06203 «Электроника и телекоммуникации»",
    "ЭКОЛ": "7M05202 «Экология»",
    "ЭЭ": "8D07103 «Электроэнергетика»",
    "ЭЭI": "7M07115 «Электроэнергетика»",
    "ЭЭJ": "8D07103 «Электроэнергетика»",
    "Ю": "7M04201 «Юриспруденция»",
    "ЮI": "7M04202 «Юриспруденция»",
    "ЮIJ": "7M04202 «Юриспруденция»",
    "ЮJ": "7M04201 «Юриспруденция»",
}


def derive_program(group: str) -> str:
    if not group:
        return ""
    m = re.match(r"\s*([А-Яа-яA-Za-z]+)", group)
    if not m:
        return ""
    prefix = m.group(1).upper()
    return PROGRAM_MAP.get(prefix, "")


def short_program_name(code_and_title: str) -> str:
    """`6B06104 «Информационные системы»` -> `Информационные системы`."""
    if not code_and_title:
        return ""
    # Извлекаем текст из «кавычек»
    m = re.search(r"[«\"]([^«»\"]+)[»\"]", code_and_title)
    if m:
        return m.group(1).strip()
    # Убираем код вида 6B06104 / 7M06102 / 8D06101 в начале строки
    cleaned = re.sub(r"^\s*[6-8][BMD]\d{5,6}\s*", "", code_and_title).strip()
    return cleaned if cleaned else code_and_title.strip()


def enrich_row(row: DisciplineRow, plan_data: dict | None = None) -> DisciplineRow:
    """Обогащает строку: кредиты и соответствие.

    plan_data (из страницы Приложения) имеет приоритет над discipline_db.
    """
    # Build DisciplineInfo from plan_data or DB
    info = None
    if plan_data and row.discipline:
        entry = plan_data.get(row.discipline)
        if entry is None and _ddb:
            # Try fuzzy match within plan_data keys
            for key in plan_data:
                candidate = _ddb.fuzzy_lookup(key)
                if candidate and _ddb.fuzzy_lookup(row.discipline) and (
                    candidate.name == _ddb.fuzzy_lookup(row.discipline).name
                ):
                    entry = plan_data[key]
                    break
        if entry:
            if _ddb:
                from discipline_db import DisciplineInfo
                info = DisciplineInfo(
                    name=row.discipline,
                    credits=int(entry.get("credits") or 0),
                    lec=int(entry.get("lec") or 0),
                    prac=int(entry.get("prac") or 0),
                    lab=int(entry.get("lab") or 0),
                    sro=int(entry.get("sro") or 0),
                )

    if info is None and _ddb:
        info = _ddb.fuzzy_lookup(row.discipline)

    if info is None:
        return row

    # Fill credits if missing
    credits_val = str(info.credits) if info.credits else row.plan_credits
    if not row.plan_credits or row.plan_credits == "0":
        row = DisciplineRow(
            discipline=row.discipline, plan_credits=credits_val,
            courses=row.courses, total_hours=row.total_hours,
            grade_points=row.grade_points, compliance=row.compliance,
            note=row.note, final_grade=row.final_grade,
        )

    # Calculate compliance
    if row.compliance in ("", "полное", "частичное") and _ddb:
        cert_hours_total = sum(
            _ddb.parse_cert_hours(c.hours) for c in row.courses if c.hours
        )
        computed = _ddb.compliance_status(info, cert_hours_total)
        if computed:
            row = DisciplineRow(
                discipline=row.discipline, plan_credits=row.plan_credits,
                courses=row.courses, total_hours=row.total_hours,
                grade_points=row.grade_points, compliance=computed,
                note=row.note, final_grade=row.final_grade,
            )
    return row


def format_student_name(name: str) -> str:
    """Форматирует ФИО как в референсе: «Фамилия Имя\\nОтчество».

    Понимает оба порядка: «Фамилия Имя Отчество» (типично для рус. документов)
    и «Имя Фамилия» (часто возвращает OCR).
    Сокращения вроде «Сычёв В.А.» оставляем как есть.
    """
    if not name:
        return ""
    s = re.sub(r"\s+", " ", name).strip()
    if "." in s:
        return s
    parts = s.split(" ")
    if len(parts) == 3:
        return f"{parts[0]} {parts[1]}\n{parts[2]}"
    if len(parts) == 2:
        # Эвристика: славянские фамилии часто оканчиваются на -ов/-ев/-ин/-ский/-ёв/-ук
        surn_suffixes = ("ов", "ев", "ёв", "ин", "ын", "ий", "ский", "цкий", "ук", "юк", "енко", "ко")
        if parts[1].lower().endswith(surn_suffixes) and not parts[0].lower().endswith(surn_suffixes):
            return f"{parts[1]} {parts[0]}"
    return s


# ---------------------------------------------------------------------------
# Row helpers: hours / grades aggregation
# ---------------------------------------------------------------------------
def sum_hours_text(entries: list[CourseEntry]) -> str:
    """Сумма часов первых чисел из hours каждого курса. Для строки с одной дисциплиной."""
    total = 0
    found = False
    for e in entries:
        m = re.search(r"(\d+(?:[.,]\d+)?)", e.hours)
        if m:
            try:
                total += int(float(m.group(1).replace(",", ".")))
                found = True
            except ValueError:
                pass
    return f"{total} ч" if found else ""


def list_hours_text(entries: list[CourseEntry]) -> str:
    """Часы каждого курса по строкам. Используется в строке «не сопоставлено»."""
    lines = [e.hours.strip() or "—" for e in entries if e.course_title.strip()]
    return "\n".join(lines)


# def list_grades_text(entries: list[CourseEntry]) -> str:
#     """Баллы/оценки каждого курса по строкам."""
#     lines = [e.grade.strip() or "—" for e in entries if e.course_title.strip()]
#     return "\n".join(lines)


# ---------------------------------------------------------------------------
# DOCX rendering
# ---------------------------------------------------------------------------
# Заголовки пишем ТОЛЬКО в «ведущие» ячейки (после мерджа).
# Иначе при merge() Word склеивает текст из всех донорских ячеек и шапка дублируется.
# Ключ — индекс «ведущей» (top-left) ячейки.
HEADERS_ROW_1_AT: dict[int, str] = {
    0: "№",
    1: "ФИО обучающегося",
    2: "Код и наименование ОП",
    3: "Курс",
    4: "По учебному плану СКУ им.М.Козыбаева",       # объединена 4-5
    6: "Фактически изучено претендентом и рассмотрено экспертной группой",  # 6-8
    9: "Заключение экспертной группы",               # 9-10
    11: "Зачтенная оценка по дисциплине учебного плана",
}
HEADERS_ROW_2_AT: dict[int, str] = {
    4: "Наименование перезачитываемых дисциплин и видов учебной работы",
    5: "Количество кредитов",
    6: "Наименование курса неформального обучения (наименование, номер, количество часов)",
    7: "Количество кредитов (часов)",
    8: "Баллы (оценка)",
    9: "Соответствие целей программы обучения, объёма программы и оценки (полное, частичное, не соответствует)",
    10: "Примечание",
}
MERGE_SPANS = [
    # (row_idx, start_col, end_col) — групповые шапки в row0
    (0, 4, 5),    # По учебному плану
    (0, 6, 8),    # Фактически
    (0, 9, 10),   # Заключение
]
MERGE_DOWN_COLS = [0, 1, 2, 3, 11]  # колонки, где row0 объединяется с row1


# Шрифт во всём документе — Times New Roman 12pt
FONT_NAME = "Times New Roman"
TABLE_FONT_SIZE_PT = 12
HEADER_FONT_SIZE_PT = 12

# Ширины колонок (см) — пропорции из ЭЗ_Умербеков_Н_ИС-у-25.docx,
# отмасштабированные под A4 landscape с полями 2/2 (доступно 25.7 см)
# Ширины 1-в-1 как в референсе ЭЗ_Умербеков_Н_ИС-у-25.docx (сумма 28.25 см).
# Чтобы таблица влезла без обрезания, поля страницы делаем 1.0 см.
COL_WIDTHS_CM: list[float] = [
    0.6,   # №
    3.0,   # ФИО
    2.3,   # ОП
    0.8,   # Курс
    3.5,   # Дисциплина
    1.0,   # Кредиты
    4.8,   # Курсы
    1.0,   # Часы
    1.6,   # Баллы
    2.8,   # Соответствие
    0.8,   # Примечание
    2.0,   # Итог
]





def _set_cell_margins(table, top=50, left=50, bottom=50, right=50):
    from docx.oxml import OxmlElement

    tbl = table._tbl
    tblPr = tbl.tblPr

    tblCellMar = tblPr.find(qn('w:tblCellMar'))
    if tblCellMar is None:
        tblCellMar = OxmlElement('w:tblCellMar')
        tblPr.append(tblCellMar)

    for m, v in [('top', top), ('left', left), ('bottom', bottom), ('right', right)]:
        node = tblCellMar.find(qn(f'w:{m}'))
        if node is None:
            node = OxmlElement(f'w:{m}')
            tblCellMar.append(node)
        node.set(qn('w:w'), str(v))
        node.set(qn('w:type'), 'dxa')










# Колонки данных, которые выравниваем по центру (короткие числовые поля).
# Остальные — по левому краю.
DATA_ALIGN_CENTER = {0, 3, 5, 7, 8, 9, 10, 11}

def _apply_font(run, *, bold: bool, size_pt: int) -> None:
    """Times New Roman, нужный размер, опц. жирный — включая cs/eastAsia, чтобы Word везде применил."""
    run.font.name = FONT_NAME
    run.font.size = Pt(size_pt)
    run.bold = bold
    # python-docx по умолчанию ставит только w:rFonts/@w:ascii. Чтобы шрифт
    # точно применился к кириллице, дублируем cs/hAnsi/eastAsia.
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        from docx.oxml import OxmlElement
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), FONT_NAME)


def _set_cell_text(
    cell,
    text: str,
    *,
    bold: bool = False,
    align_center: bool = True,  # по умолчанию все ячейки таблицы — по центру
    size_pt: int = TABLE_FONT_SIZE_PT,
) -> None:
    cell.text = ""
    para = cell.paragraphs[0]
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER if align_center else WD_ALIGN_PARAGRAPH.LEFT
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP

    # Все строки идут в ОДНОМ параграфе через line-break — иначе Word
    # добавляет вертикальные отступы между параграфами и ячейка раздувается.
    lines = str(text).split("\n")
    for li, line in enumerate(lines):
        if li > 0:
            br_run = para.add_run()
            _apply_font(br_run, bold=bold, size_pt=size_pt)
            br_run.add_break()
        run = para.add_run(line)
        _apply_font(run, bold=bold, size_pt=size_pt)


def _set_landscape(section) -> None:
    # Явно A4 landscape (29.7 × 21 см), а не US Letter
    section.page_width = Cm(29.7)
    section.page_height = Cm(21.0)
    # Поля 1 см / 1 см L/R чтобы таблица 28.25 см влезла без обрезания.
    section.left_margin = Cm(1.0)
    section.right_margin = Cm(1.0)
    section.top_margin = Cm(1.5)
    section.bottom_margin = Cm(1.5)


def _set_col_widths(table, widths_cm: list[float]) -> None:
    """Жёстко задаём ширину каждой колонки во всех строках (после merges)."""
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            if i < len(widths_cm):
                cell.width = Cm(widths_cm[i])
    # Дополнительно: фиксируем layout=fixed чтобы Word не перерастягивал
    from docx.oxml import OxmlElement
    tbl_pr = table._tbl.tblPr
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")


def _add_borders(table) -> None:
    from docx.oxml import OxmlElement
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "4")
            el.set(qn("w:color"), "000000")
            borders.append(el)
        tbl_pr.append(borders)


def build_report(payload: ReportPayload, plan_data: dict | None = None) -> bytes:
    doc = Document()
    _set_landscape(doc.sections[0])

    # Дефолтный шрифт документа — Times New Roman 12pt
    style = doc.styles["Normal"]
    style.font.name = FONT_NAME
    style.font.size = Pt(TABLE_FONT_SIZE_PT)
    # Для надёжности дублируем имя шрифта в rPrDefault
    from docx.oxml import OxmlElement
    rpr_default = style.element.get_or_add_rPr()
    rfonts = rpr_default.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr_default.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), FONT_NAME)

    # Заголовок
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("Экспертное заключение")
    _apply_font(run, bold=True, size_pt=12)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_run = sub.add_run(
        "по определению соответствия результатов неформального обучения по профилю подготовки"
    )
    _apply_font(sub_run, bold=True, size_pt=12)

    doc.add_paragraph("")

    rows_data = [enrich_row(r, plan_data) for r in (payload.rows or [DisciplineRow()])]

    table = doc.add_table(rows=2 + len(rows_data), cols=12)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    # СНАЧАЛА мерджим (чтобы не дублировался текст), ПОТОМ пишем
    for r, s, e in MERGE_SPANS:
        table.rows[r].cells[s].merge(table.rows[r].cells[e])
    for col in MERGE_DOWN_COLS:
        table.rows[0].cells[col].merge(table.rows[1].cells[col])

    # Заголовки — только в ведущие ячейки
    for ci, h in HEADERS_ROW_1_AT.items():
        _set_cell_text(
            table.rows[0].cells[ci], h, align_center=True,
            size_pt=HEADER_FONT_SIZE_PT,
        )
    for ci, h in HEADERS_ROW_2_AT.items():
        _set_cell_text(
            table.rows[1].cells[ci], h, align_center=True,
            size_pt=HEADER_FONT_SIZE_PT,
        )

    student_name_fmt = format_student_name(payload.student_name)
    program_short = payload.program_code or ""

    for ri, row_data in enumerate(rows_data, start=2):
        cells = table.rows[ri].cells
        # Группой считаем строку с >1 курсом (типичный случай — «не сопоставлено»)
        is_group = len(row_data.courses) > 1
        courses_text = "\n".join(
            c.format() for c in row_data.courses if c.course_title.strip()
        ) or ""
        compliance = row_data.compliance or ("" if is_group else "полное")
        if is_group:
            hours_cell = row_data.total_hours or sum_hours_text(row_data.courses)
            #grade_cell = row_data.grade_points or list_grades_text(row_data.courses)
            grade_cell=""
        else:
            hours_cell = row_data.total_hours or sum_hours_text(row_data.courses)
            grade_cell = row_data.grade_points or (
            row_data.courses[0].grade.strip() if row_data.courses else ""
            )

        values = [
            str(ri - 1),           # 0  №
            student_name_fmt,      # 1  ФИО
            program_short,         # 2  ОП
            payload.course_year,   # 3  Курс
            row_data.discipline,   # 4  Дисциплина
            row_data.plan_credits, # 5  Кредиты
            courses_text,          # 6  Курсы
            hours_cell,            # 7  Часы
            grade_cell,            # 8  Баллы
            compliance,            # 9  Соответствие
            row_data.note,         # 10 Примечание
            row_data.final_grade,  # 11 Зачт. оценка
        ]
        for ci, v in enumerate(values):
            _set_cell_text(cells[ci], v, align_center=(ci in DATA_ALIGN_CENTER))

    _set_col_widths(table, COL_WIDTHS_CM)
    _add_borders(table)
    _set_cell_margins(table)

    # Подписи экспертов — формат как в референсе: длинные с табами/nbsp
    doc.add_paragraph("")
    expert_head = doc.add_paragraph()
    expert_head.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    _apply_font(expert_head.add_run("Эксперты:"), bold=True, size_pt=TABLE_FONT_SIZE_PT)
    nbsp = "\u00a0"
    for expert in payload.experts:
        line = doc.add_paragraph()
        line.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        run = line.add_run(
            f"{expert}\t{nbsp*7}______________{nbsp*4}______________"
        )
        _apply_font(run, bold=False, size_pt=TABLE_FONT_SIZE_PT)
        sub = doc.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        sub_run = sub.add_run(
            f"\t\t\t(ФИО, должность)\t\t\t\t\t{nbsp*10}(подпись)\t{nbsp*27}(дата)"
        )
        _apply_font(sub_run, bold=False, size_pt=10)
        sub_run.italic = True

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
