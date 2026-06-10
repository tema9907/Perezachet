"""
Верификация сертификатов по URL: извлечение часов/названия курса
с сайтов провайдеров (Coursera, Udemy, Stepik, edX и др.).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

log = logging.getLogger("cert_verifier")

_TIMEOUT = 12.0
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# Known provider URL patterns
_URL_PATTERNS: list[re.Pattern] = [
    re.compile(r"https?://(?:www\.)?coursera\.org/(?:account/accomplishments/verify|verify)/[\w-]+", re.I),
    re.compile(r"https?://(?:www\.)?udemy\.com/certificate/[\w-]+/?", re.I),
    re.compile(r"https?://stepik\.org/cert/\d+", re.I),
    re.compile(r"https?://(?:courses?\.)?edx\.org/certificates?/[\w-]+", re.I),
    re.compile(r"https?://(?:www\.)?credential\.net/[\w-]+", re.I),
    re.compile(r"https?://(?:www\.)?linkedin\.com/learning/certificates?/[\w-]+", re.I),
    re.compile(r"https?://(?:www\.)?datacamp\.com/certificate/[\w-]+", re.I),
    re.compile(r"https?://alison\.com/certification/check/\d+", re.I),
    re.compile(r"https?://skillbox\.ru/certificate/[\w-]+", re.I),
    re.compile(r"https?://intuit\.ru/(?:verificate|studies|certificate)/[\w/-]+", re.I),
    re.compile(r"https?://openedu\.ru/certificate/[\w/-]+", re.I),
]

_GENERAL_CERT_RE = re.compile(
    r"https?://[^\s<>\"'()]+(?:certif|verify|accomplishment|credential|diploma)[\w/-]*",
    re.I,
)


def extract_cert_urls(text: str) -> list[str]:
    """Извлекает URL верификации сертификатов из текста."""
    seen: set[str] = set()
    result: list[str] = []

    def _add(url: str) -> None:
        url = url.rstrip(".,;)'\"")
        if url and url not in seen and len(url) > 20:
            seen.add(url)
            result.append(url)

    for pattern in _URL_PATTERNS:
        for m in pattern.finditer(text):
            _add(m.group(0))
    for m in _GENERAL_CERT_RE.finditer(text):
        _add(m.group(0))
    return result


# ---------------------------------------------------------------------------
# Helpers: hours from various HTML sources
# ---------------------------------------------------------------------------
def _hours_from_text(text: str) -> float | None:
    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*(?:academic\s*)?(?:hour|hours|hr|hrs)\b",
        r"(\d+(?:[.,]\d+)?)\s*(?:астроном\w*|академич\w*)?\s*(?:час|часов|часа|ч\.)\b",
        r"(?:Duration|Длительность|Продолжительность)[:\s]+(\d+(?:[.,]\d+)?)(?:\s*h|\s*hours?|\s*ч|\s*час)",
        r"(?:Time to complete|Время прохождения)[:\s]+(\d+(?:[.,]\d+)?)\s*(?:h|hours?|ч|час)",
        r"(\d{1,3})\s*(?:hours?|ч(?:асов?)?)\s+of\s+content",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            try:
                val = float(m.group(1).replace(",", "."))
                if 0 < val < 10000:  # sanity check
                    return val
            except ValueError:
                pass
    return None


def _hours_from_json_ld(html: str) -> float | None:
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.I
    ):
        try:
            data = json.loads(m.group(1))
            for key in ("timeRequired", "duration"):
                val = data.get(key, "")
                if val:
                    dm = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", str(val))
                    if dm:
                        h = int(dm.group(1) or 0) + int(dm.group(2) or 0) / 60
                        if h > 0:
                            return h
            for key in ("hours", "totalHours", "numberOfHours", "studyLoad"):
                val = data.get(key)
                if val:
                    try:
                        return float(str(val).replace(",", "."))
                    except ValueError:
                        pass
        except Exception:
            pass
    return None


def _hours_from_next_data(html: str) -> float | None:
    m = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.I)
    if not m:
        return None
    try:
        raw = json.dumps(json.loads(m.group(1)), ensure_ascii=False)
        return _hours_from_text(raw)
    except Exception:
        return None


def _title_from_html(html: str) -> str:
    # og:title
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', html, re.I)
    if m:
        return m.group(1).strip()
    # <title>
    m = re.search(r'<title[^>]*>([^|<]+)', html, re.I)
    if m:
        return m.group(1).strip()
    return ""


# ---------------------------------------------------------------------------
# Fetch & parse
# ---------------------------------------------------------------------------
def _fetch(url: str) -> tuple[int, str]:
    """Возвращает (http_status, html). status=0 при сетевой ошибке."""
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
            r = client.get(url)
            log.info("  HTTP %d ← %s", r.status_code, url[:100])
            return r.status_code, r.text
    except Exception as e:
        log.warning("  fetch error for %s: %s", url[:80], e)
    return 0, ""


def _parse_html(html: str) -> dict[str, Any]:
    if not html:
        return {}
    info: dict[str, Any] = {}
    hours = _hours_from_json_ld(html)
    if not hours:
        hours = _hours_from_next_data(html)
    if not hours:
        clean = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.I)
        clean = re.sub(r"<script[^>]*>.*?</script>", " ", clean, flags=re.DOTALL | re.I)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = re.sub(r"\s+", " ", clean)
        hours = _hours_from_text(clean)
    if hours and hours > 0:
        info["hours"] = hours
    title = _title_from_html(html)
    if title:
        info["course_title"] = title
    return info


# Паттерны soft-404 в <title> и og:title (рендерятся SSR, надёжнее тела страницы)
_NOT_FOUND_TITLE_PATTERNS: tuple[str, ...] = (
    "интересное открытие",
    "interesting discovery",
    "page not found",
    "страница не найдена",
    "not found",
    "404",
    "doesn't exist",
    "не существует",
)

# Паттерны в теле страницы (для серверных страниц без SPA)
_NOT_FOUND_BODY_PATTERNS: tuple[str, ...] = (
    "интересное открытие",
    "interesting discovery",
    "вы нашли несуществующую",
    "you've found a page that doesn't exist",
    "this certificate does not exist",
    "certificate not found",
    "no certificate found",
    "we couldn't find the page",
    "мы не можем найти эту страницу",
    "такой страницы не существует",
    "запрашиваемая страница не найдена",
    # Next.js / JSON state embeds
    '"statusCode":404',
    '"status":404',
    '"notFound":true',
)


def is_not_found_page(html: str) -> bool:
    """Возвращает True если страница — soft-404 / «не найдено».

    Проверяет <title>/og:title (SSR-надёжно) + тело страницы (для не-SPA).
    Для SPA (Coursera) основной сигнал — HTTP 404, которое обрабатывается
    до вызова этой функции в fetch_cert_info.
    """
    if not html:
        return False
    # Проверяем <title> / og:title — они всегда в SSR-HTML
    title = _title_from_html(html).lower()
    if any(p in title for p in _NOT_FOUND_TITLE_PATTERNS):
        log.info("  not-found detected via title: %r", title[:80])
        return True
    # Проверяем тело
    lower = html.lower()
    for p in _NOT_FOUND_BODY_PATTERNS:
        if p in lower:
            log.info("  not-found detected via body pattern: %r", p)
            return True
    return False


def fetch_cert_info(url: str) -> dict[str, Any]:
    """Загружает страницу верификации сертификата и возвращает данные.

    Возвращает dict с ключами:
      - hours (float), course_title (str) — если найдено.
      - not_found (True) — если страница вернула «не найдено» / HTTP 404 / soft-404.
    Возвращает {} если страница недоступна или данных нет.
    """
    if not url:
        return {}
    log.info("▶ cert URL check: %s", url)
    status, html = _fetch(url)

    # HTTP 404 — точный сигнал «не найдено»
    if status == 404:
        log.info("  → not_found (HTTP 404)")
        return {"not_found": True}

    # Сетевая ошибка или неожиданный статус — не считаем «не найдено»
    if status == 0 or status not in (200, 301, 302):
        log.info("  → fetch failed or unexpected status %d", status)
        return {}

    # Soft-404: сервер вернул 200 но страница — «не найдено»
    if is_not_found_page(html):
        log.info("  → not_found (soft-404 detected in HTML)")
        return {"not_found": True}

    info = _parse_html(html)
    if info:
        log.info("  → found data: %s", info)
    else:
        log.info("  → page OK but no cert data extracted")
    return info
