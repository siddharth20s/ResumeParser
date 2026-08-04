from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

from dateutil import parser as date_parser

_PRESENT_TOKENS = {"present", "current", "now", "today"}


def normalize_text(text: str) -> str:
    value = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    # Join wrapped words split by PDF extraction, e.g. "zero-\ndowntime" or URL path fragments.
    value = re.sub(r"([A-Za-z0-9])\-\n([A-Za-z0-9])", r"\1-\2", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)

    return ordered


def parse_date_token(token: str) -> date | None:
    cleaned = re.sub(r"[.,]", " ", token).strip()
    if not cleaned:
        return None

    if cleaned.casefold() in _PRESENT_TOKENS:
        return date.today()

    if re.fullmatch(r"\d{4}", cleaned):
        try:
            return date(int(cleaned), 1, 1)
        except ValueError:
            return None

    try:
        parsed = date_parser.parse(cleaned, fuzzy=True, default=datetime(1900, 1, 1))
        return parsed.date()
    except Exception:
        return None


def to_iso_month(value: date | None) -> str | None:
    if value is None:
        return None
    return f"{value.year:04d}-{value.month:02d}"


def month_delta(start: date | None, end: date | None) -> int | None:
    if start is None or end is None:
        return None
    delta = (end.year - start.year) * 12 + (end.month - start.month)
    return max(0, delta)


def clip_text(value: str, limit: int = 1400) -> str:
    trimmed = value.strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[: limit - 3].rstrip() + "..."


def safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 3)
