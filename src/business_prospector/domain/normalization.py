from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    ascii_text = text.encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(ascii_text.split())


def slugify(value: str) -> str:
    slug = _NON_ALNUM.sub("-", normalize_text(value)).strip("-")
    if not slug:
        raise ValueError("name must contain at least one letter or number")
    return slug


def normalize_phone(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) in (10, 11):
        digits = "55" + digits
    return digits


def normalize_domain(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    parsed = urlsplit(raw if "://" in raw else "https://" + raw)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def normalize_address(value: str | None) -> str | None:
    normalized = normalize_text(value)
    return normalized or None

