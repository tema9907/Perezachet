"""Клиент к is.ku.edu.kz (e-Rectorat / Учебные планы).

Тянет с сайта:
  1. Селекты (Факультет / Специальность / Поток / Курс / Год / Форма) — надёжно.
  2. Учебный план целевой программы (список дисциплин с кредитами) — server-side
     рендер `default.asp?Find=Yes&...`.

ВАЖНО: сайт на классическом ASP (IIS, NTLM-аутентификация, кодировка cp1251).
Их backend НЕСТАБИЛЕН: на некоторых комбинациях специальность/поток/курс он
падает с `Microsoft VBScript error '800a0009'` (Индекс вне диапазона) на выводе
строк плана, а на пустых — отдаёт «НЕТ ДАННЫХ!». Поэтому:
  - fetch_plan() возвращает структуру со статусом ('ok' | 'no_data' | 'server_error'),
  - вызывающий код при 'no_data'/'server_error' предлагает эксперту ручную вставку.
"""
from __future__ import annotations

import html as _html
import os
import re
import time
from typing import Any

import requests

try:
    from requests_ntlm import HttpNtlmAuth
    _HAS_NTLM = True
except ImportError:  # pragma: no cover
    HttpNtlmAuth = None  # type: ignore
    _HAS_NTLM = False

try:
    import urllib3
    urllib3.disable_warnings()
except Exception:  # pragma: no cover
    pass

from syslog import log

BASE_URL = "https://is.ku.edu.kz/e-Rectorat/LPlans/default.asp"
DEFAULT_FACULTY = os.environ.get("KU_FACULTY", "58")  # ФИЦТ


def current_year() -> int:
    """Текущий календарный год (или KU_YEAR из .env, если задан)."""
    env = os.environ.get("KU_YEAR")
    if env and env.isdigit():
        return int(env)
    return time.localtime().tm_year


DEFAULT_YEAR = str(current_year())

# Семестры 1..8, как в рабочем запросе. ВАЖНО: план тянем с Form=0 и Stream=0
# (ВСЕ формы/потоки) — именно эта комбинация НЕ роняет их ASP (в отличие от
# Form=1 + конкретный Stream, где сервер падает с VBScript '800a0009').
_SEM2 = "".join(f"&Semester2={i}" for i in range(1, 9))


class KuError(RuntimeError):
    """Базовая ошибка обращения к is.ku.edu.kz."""


class KuAuthError(KuError):
    """Не заданы учётные данные либо 401."""


class KuServerError(KuError):
    """Сервер вуза упал при рендере плана (их VBScript-баг / HTTP 500)."""


class KuNoData(KuError):
    """Для выбранной комбинации на сайте нет плана («НЕТ ДАННЫХ!»)."""


def _credentials() -> tuple[str, str]:
    u = os.environ.get("KU_USERNAME", "").strip()
    p = os.environ.get("KU_PASSWORD", "").strip()
    if not u or not p:
        raise KuAuthError(
            "Не заданы KU_USERNAME / KU_PASSWORD (учётные данные is.ku.edu.kz) в .env"
        )
    if not _HAS_NTLM:
        raise KuError("Не установлен пакет requests-ntlm (pip install requests-ntlm)")
    return u, p


def _session() -> requests.Session:
    u, p = _credentials()
    s = requests.Session()
    s.auth = HttpNtlmAuth(u, p)
    s.verify = False
    s.headers.update({"User-Agent": "NefrLearn/formal-module"})
    return s


def _get(url: str, timeout: float = 60.0) -> tuple[int, str]:
    s = _session()
    try:
        r = s.get(url, timeout=timeout)
    except requests.RequestException as e:
        raise KuError(f"Сеть/соединение с is.ku.edu.kz: {e}") from e
    if r.status_code == 401:
        raise KuAuthError("401: неверные учётные данные is.ku.edu.kz")
    text = r.content.decode("cp1251", "replace")
    return r.status_code, text


# ---------------------------------------------------------------------------
# Разбор <select> с сайта
# ---------------------------------------------------------------------------
def _parse_options(page: str, select_name: str) -> list[dict[str, str]]:
    """Достаёт <option value=..>label из <select name=select_name>.

    Опции идут в формате `<option value=976 >6B06104  Название` (без кавычек).
    """
    m = re.search(
        r"<select[^>]*\bname=%s\b(.*?)</select>" % re.escape(select_name),
        page, re.S | re.I,
    )
    if not m:
        return []
    block = m.group(1)
    out: list[dict[str, str]] = []
    for om in re.finditer(
        r"<option\s+value=['\"]?([^'\"\s>]*)['\"]?[^>]*>([^<]*)", block, re.S | re.I
    ):
        value = om.group(1).strip()
        label = _html.unescape(re.sub(r"\s+", " ", om.group(2))).strip()
        if label:
            out.append({"value": value, "label": label})
    return out


def fetch_selects(faculty: str = DEFAULT_FACULTY) -> dict[str, list[dict[str, str]]]:
    """Загружает страницу факультета и парсит все справочники-селекты."""
    status, page = _get(f"{BASE_URL}?Faculty={faculty}")
    if status >= 500:
        raise KuServerError(f"is.ku.edu.kz вернул HTTP {status}")
    result = {
        name.lower(): _parse_options(page, name)
        for name in ("Faculty", "Speciality", "Stream", "Course", "Year", "Form", "Cycle")
    }
    log(
        f"ku_plans: селекты факультета {faculty} — "
        f"специальностей={len(result['speciality'])}, потоков={len(result['stream'])}"
    )
    return result


# ---------------------------------------------------------------------------
# Учебный план
# ---------------------------------------------------------------------------
def _build_plan_url(*, faculty: str, speciality: str, year: str = DEFAULT_YEAR,
                    stream_id: str = "0") -> str:
    """URL плана. Form=0 всегда. Stream=0 → весь план (устойчиво), либо конкретный id.

    ВНИМАНИЕ: некоторые потоки (ускоренные «-у-») роняют их ASP даже при Form=0 —
    это отлавливается как server_error.
    """
    # Course=0 (ВСЕ курсы) — критично: Course=1 в связке с конкретным Stream роняет их
    # ASP на ускоренных потоках («-у-»). Тянем весь план потока, курс фильтруем у себя.
    return (
        f"{BASE_URL}?Find=Yes"
        f"&Faculty={faculty}&Form=0&Course=0"
        f"&Speciality={speciality}&Stream={stream_id or '0'}"
        f"&Chair=0&Lang=0&Cycle=0&ControlType=0&Credd=&CreddSem=&DisciplineName="
        f"&Year={year}&Sem=0&Semester=-1&Semester=-2&SemesterAll=true{_SEM2}&Sort="
    )


def _cells(segment: str) -> list[str]:
    """Разбирает ячейки одной строки; ASP часто не закрывает <td>/</tr>."""
    cells: list[str] = []
    for c in re.findall(
        r"<t[dh][^>]*>(.*?)(?=<t[dh]|</tr|<tr|</table|$)", segment + "$", re.S | re.I
    ):
        txt = _html.unescape(re.sub(r"<[^>]+>", " ", c))
        txt = txt.replace("\xa0", " ")
        cells.append(re.sub(r"\s+", " ", txt).strip())
    return cells


def _semesters(cell_exam: str, cell_assess: str) -> set[int]:
    """Семестры дисциплины = числа из колонок «Экз.» ∪ «Оц./атт.»."""
    nums: set[int] = set()
    for c in (cell_exam, cell_assess):
        for d in re.findall(r"\d+", c or ""):
            n = int(d)
            if 1 <= n <= 12:
                nums.add(n)
    return nums


def parse_plan_rows(page: str) -> list[dict[str, Any]]:
    """Парсит таблицу учебного плана в список дисциплин.

    Колонки: 0 Каф.|1 Поток|2 Дисциплина|3 Шифр|4 Спец-я|5 Цикл|6 В нагрузке|
    7 Экз.|8 Оц./атт.|9 КР/КП|10 Кред.|11 Кред. в сем.|... Берём название, кредиты,
    цикл, шифр, ПОТОК и СЕМЕСТРЫ (для фильтра по курсу).
    """
    hdr = re.search(r"Дисциплина.*?Кред", page, re.S)
    body = page[hdr.start():] if hdr else page

    rows: list[dict[str, Any]] = []
    for seg in re.split(r"<tr", body, flags=re.I)[1:]:
        cells = _cells(seg)
        if len(cells) < 11:
            continue
        name = cells[2].strip()
        if not name or len(name) < 3 or not re.search(r"[A-Za-zА-Яа-яӘәҚқ]", name):
            continue
        if name.lower().startswith(("дисциплина", "каф", "№")):
            continue
        cm = re.search(r"\d+", cells[10]) if len(cells) > 10 else None
        sems = _semesters(cells[7] if len(cells) > 7 else "",
                          cells[8] if len(cells) > 8 else "")
        rows.append({
            "name": name,
            "credits": cm.group(0) if cm else "",
            "cycle": cells[5] if len(cells) > 5 else "",
            "code": cells[3] if len(cells) > 3 else "",
            "stream": cells[1] if len(cells) > 1 else "",
            "semesters": sorted(sems),
        })
    return rows


def _is_server_crash(status: int, page: str) -> bool:
    return (
        status >= 500
        or "800a0009" in page
        or "Microsoft VBScript" in page
        or "ûïîëíåíèÿ" in page  # cp1251-текст ошибки как мохибейк
    )


def filter_plan(rows: list[dict[str, Any]], *, courses: list[int] | None = None,
                stream_label: str = "") -> list[dict[str, Any]]:
    """Фильтрует распарсенный план: по потоку (если задан) и по курсам, + дедуп.

    courses=[1] → семестры {1,2}; [1,2] → {1,2,3,4}. None → все.
    """
    wanted: set[int] | None = None
    if courses:
        wanted = set()
        for c in courses:
            wanted |= {2 * c - 1, 2 * c}

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        if stream_label and r.get("stream", "").strip() and \
                r["stream"].strip().lower() != stream_label.strip().lower():
            continue
        if wanted is not None:
            sems = set(r.get("semesters") or [])
            if sems and not (sems & wanted):
                continue  # есть семестры, но не нашего курса
            # дисциплины без семестров (редкие) — пропускаем при фильтре по курсу
            if not sems:
                continue
        key = re.sub(r"\s+", " ", r["name"].strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return _merge_variants(out)


def _base_name(name: str) -> str:
    """«Модуль ... (политология)» → «Модуль ...»; убираем скобочный компонент."""
    return re.sub(r"\s*\(.*$", "", name or "").strip()


def _credits_int(row: dict[str, Any]) -> int:
    try:
        return int(re.sub(r"\D", "", row.get("credits") or "0") or 0)
    except ValueError:
        return 0


def _components(name: str) -> list[str]:
    """«Модуль ... (политология, социология)» → ['политология', 'социология']."""
    m = re.search(r"\(([^)]*)\)", name or "")
    if not m:
        return []
    return [c.strip() for c in m.group(1).split(",") if c.strip()]


# Модуль социально-политических знаний в нагрузке СКУ приходит 5 строками:
# 4 компонента по 2 кр. (культурология/политология/психология/социология) + сводная
# строка «(политология, социология, культурология, психология)» на 8 кр.
_SOCPOL_RE = re.compile(r"модул[ья].*социальн\w*[-\s]*полит", re.I)
_PSY_RE = re.compile(r"психолог", re.I)


def _split_socpol(grp: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Модуль соц.-полит. знаний → модуль БЕЗ психологии + «Психология» отдельной строкой.

    Психология в СКУ ведётся отдельной кафедрой и перезачитывается самостоятельно,
    поэтому её нельзя прятать внутрь модуля. Кредиты модуля = сводные минус психология
    (8 − 2 = 6); если сводной строки нет — сумма остальных компонентов.
    Возвращает None, если компонента «психология» в группе нет (тогда обычный merge).
    """
    psy = next((r for r in grp
                if len(_components(r["name"])) == 1
                and _PSY_RE.search(_components(r["name"])[0])), None)
    if not psy:
        return None
    agg = max(grp, key=lambda r: len(_components(r["name"])))
    psy_credits = _credits_int(psy)
    if len(_components(agg["name"])) > 1:
        module_credits = _credits_int(agg) - psy_credits
    else:
        module_credits = sum(_credits_int(r) for r in grp
                             if r is not psy and len(_components(r["name"])) == 1)

    module = dict(agg)
    module["name"] = _base_name(agg["name"]) or _base_name(grp[0]["name"])
    if module_credits > 0:
        module["credits"] = str(module_credits)
    psychology = dict(psy)
    psychology["name"] = "Психология"
    log(f"ku_plans: «{module['name']}» разделён — модуль {module['credits']} кр. + "
        f"Психология {psychology.get('credits')} кр.")
    return [module, psychology]


def _merge_variants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Схлопывает компоненты-варианты одной дисциплины (напр. модули соц.-пол. знаний,
    идущие как 4-5 строк «(культурология)/(политология)/…») в одну строку с макс.
    кредитами. Дисциплины без повторов базового имени остаются как есть (с их скобками).

    Исключение — модуль социально-политических знаний: он разделяется на сам модуль
    и отдельную дисциплину «Психология» (см. _split_socpol).
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for r in rows:
        b = _base_name(r["name"]).lower()
        if b not in groups:
            groups[b] = []
            order.append(b)
        groups[b].append(r)
    merged: list[dict[str, Any]] = []
    for b in order:
        grp = groups[b]
        if _SOCPOL_RE.search(b):
            split = _split_socpol(grp)
            if split:
                merged.extend(split)
                continue
        if len(grp) <= 1:
            merged.append(grp[0])
            continue
        # несколько вариантов одного базового имени → одна строка, макс. кредиты
        best = max(grp, key=_credits_int)
        rep = dict(best)
        rep["name"] = _base_name(best["name"]) or best["name"]
        merged.append(rep)
    return merged


def pick_stream(rows: list[dict[str, Any]], year: int | None = None) -> str:
    """Авто-выбор потока: набор прошлого года от текущего.

    Текущий год 2026 → берём поток с суффиксом «-25» (например «ИС-25»).
    Из потоков плана выбираем «чистый» (буквы+«-»+YY, без (DO)/у/доп.цифр), иначе любой
    с этим суффиксом, иначе самый частый поток в плане.
    """
    if year is None:
        year = current_year()
    suffix = f"{(year - 1) % 100:02d}"  # 2026 → '25'
    labels: list[str] = []
    for r in rows:
        s = (r.get("stream") or "").strip()
        if s and s not in labels:
            labels.append(s)
    ending = [l for l in labels if l.lower().endswith("-" + suffix)]
    if ending:
        clean = [l for l in ending if re.fullmatch(r"[A-Za-zА-Яа-яЁё]+-" + suffix, l)]
        return (clean or ending)[0]
    # суффикса нет — берём самый распространённый поток (обычный, не спец-вариант)
    if labels:
        from collections import Counter
        cnt = Counter((r.get("stream") or "").strip() for r in rows if r.get("stream"))
        return cnt.most_common(1)[0][0] if cnt else labels[0]
    return ""


def fetch_plan(*, faculty: str = DEFAULT_FACULTY, speciality: str,
               courses: list[int] | None = None, stream_id: str = "0",
               stream_label: str = "", year: str = DEFAULT_YEAR) -> dict[str, Any]:
    """Тянет план специальности с сайта и фильтрует по курсу.

    Два режима:
      • АВТО (stream_id пуст/0): тянем весь план (Stream=0) и сами выбираем поток —
        набор прошлого года от текущего (pick_stream), фильтруем по нему.
      • РУЧНОЙ (stream_id задан): тянем план конкретного потока (Stream=id) — фильтруем
        только по курсу. (Ускоренные потоки могут ронять их ASP → server_error.)

    Возвращает {status, disciplines, stream, message}. По умолчанию courses=[1].
    """
    if courses is None:
        courses = [1]
    manual = bool(stream_id) and str(stream_id) not in ("", "0")
    url = _build_plan_url(faculty=faculty, speciality=speciality, year=year,
                          stream_id=(str(stream_id) if manual else "0"))
    status, page = _get(url)

    all_rows = parse_plan_rows(page)
    if all_rows:
        if manual:
            stream = (all_rows[0].get("stream") or "").strip() or stream_label
            disciplines = filter_plan(all_rows, courses=courses, stream_label="")
        else:
            stream = stream_label.strip() or pick_stream(all_rows)
            disciplines = filter_plan(all_rows, courses=courses, stream_label=stream)
        log(f"ku_plans: план spec={speciality} — всего {len(all_rows)}, "
            f"режим={'ручной' if manual else 'авто'}, поток='{stream}', "
            f"курс{courses}: {len(disciplines)} дисц.")
        if disciplines:
            return {"status": "ok", "disciplines": disciplines, "stream": stream,
                    "message": "", "total_parsed": len(all_rows)}
        # поток не дал курс — пробуем без фильтра потока
        disciplines = filter_plan(all_rows, courses=courses, stream_label="")
        if disciplines:
            return {"status": "ok", "disciplines": disciplines, "stream": stream,
                    "message": "", "total_parsed": len(all_rows)}
        deduped = filter_plan(all_rows, courses=None, stream_label="")
        return {"status": "ok", "disciplines": deduped, "stream": stream, "message":
                "Не удалось выделить курс — показан весь план, отфильтруйте вручную.",
                "total_parsed": len(all_rows)}

    if _is_server_crash(status, page):
        msg = ("Сервер вуза упал при выводе плана этого потока (частый баг их ASP на "
               "ускоренных потоках). Выберите обычный поток или вставьте план вручную."
               if manual else
               "Сервер вуза упал при выводе плана (баг их ASP). Вставьте план вручную.")
        return {"status": "server_error", "disciplines": [], "message": msg}

    return {"status": "no_data", "disciplines": [],
            "message": "На сайте нет плана для этой специальности или он не распознан. "
                       "Вставьте вручную."}


# Версия разбора/сборки плана. Кеш хранит УЖЕ обработанные дисциплины, поэтому любое
# изменение parse_plan_rows/filter_plan/_merge_variants обязано менять это число —
# иначе старые заявления продолжат получать план, собранный прошлой логикой.
PLAN_PARSER_VERSION = 2


def cache_key(*, faculty: str, speciality: str, courses: list[int],
              stream_id: str, stream_label: str, year: str) -> str:
    tail = stream_id if (stream_id and str(stream_id) not in ("", "0")) else (stream_label or "auto")
    return (f"v{PLAN_PARSER_VERSION}|{faculty}|{speciality}|"
            f"{'-'.join(map(str, courses))}|{tail}|{year}")
