"""
Справочник дисциплин: часы лекций/практик/лаб/СРО и кредиты по учебным планам СКУ.
Данные из discipline_db.json — собраны с is.ku.edu.kz за 2025 год.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DB_PATH = Path(__file__).parent / "discipline_db.json"


@dataclass
class DisciplineInfo:
    name: str
    credits: int
    lec: int    # часы лекций
    prac: int   # часы практик
    lab: int    # часы лабораторных
    sro: int    # часы СРО

    @property
    def contact_hours(self) -> int:
        """Аудиторные часы = лекции + практики + лабораторные."""
        return self.lec + self.prac + self.lab

    @property
    def compliance_threshold(self) -> float:
        """50% от аудиторных часов — порог для признания соответствия полным."""
        return self.contact_hours * 0.5


@lru_cache(maxsize=1)
def _load_db() -> dict[str, dict]:
    if not _DB_PATH.exists():
        return {}
    with open(_DB_PATH, encoding="utf-8") as f:
        return json.load(f)


def lookup(discipline_name: str) -> DisciplineInfo | None:
    """Точный поиск по названию дисциплины."""
    db = _load_db()
    name = discipline_name.strip()
    entry = db.get(name)
    if entry is None:
        return None
    return DisciplineInfo(
        name=name,
        credits=int(entry.get("credits") or 0),
        lec=int(entry.get("lec") or 0),
        prac=int(entry.get("prac") or 0),
        lab=int(entry.get("lab") or 0),
        sro=int(entry.get("sro") or 0),
    )


def fuzzy_lookup(discipline_name: str, threshold: float = 0.6) -> DisciplineInfo | None:
    """Нечёткий поиск: ищет наилучшее совпадение по ключевым словам."""
    db = _load_db()
    name = discipline_name.strip().lower()
    if not name:
        return None

    # Exact match first (case-insensitive)
    for key in db:
        if key.lower() == name:
            return lookup(key)

    # Partial match: split into words, count overlap
    words = set(w for w in name.split() if len(w) > 3)
    if not words:
        return None

    best_score = 0.0
    best_key = None
    for key in db:
        key_words = set(w for w in key.lower().split() if len(w) > 3)
        if not key_words:
            continue
        overlap = len(words & key_words)
        score = overlap / max(len(words), len(key_words))
        if score > best_score:
            best_score = score
            best_key = key

    if best_score >= threshold and best_key:
        return lookup(best_key)
    return None


def parse_cert_hours(hours_str: str) -> float:
    """Извлекает число часов из строки вида '60 ч', '45', '30 часов' и т.п."""
    import re
    if not hours_str:
        return 0.0
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(hours_str))
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    return 0.0


def compliance_status(plan_info: DisciplineInfo | None, cert_hours_total: float) -> str:
    """Возвращает 'полное' или 'частичное' в зависимости от набранных часов."""
    if plan_info is None or plan_info.contact_hours == 0:
        return ""
    if cert_hours_total >= plan_info.compliance_threshold:
        return "полное"
    return "частичное"
