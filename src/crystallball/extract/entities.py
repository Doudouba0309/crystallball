"""Regex-based entity extraction.

Deterministic and dependency-free. The point is not to rival a trained NER
model, but to pull out the high-precision, high-value identifiers that make
unstructured documents joinable: contact addresses, references, money, dates.
Every pattern here is intentionally conservative, because a wrong join key is
worse than a missing one.
"""

from __future__ import annotations

import re

from ..models import Document, ExtractionResult
from .base import Extractor

#: Maximum values retained per field. Counts are always exact.
MAX_VALUES = 25

MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)

CURRENCY_SYMBOLS = r"USD|SGD|EUR|GBP|MYR|RM|CNY|RMB|JPY|AUD|CAD|HKD|INR|IDR|THB|PHP|VND|\$|€|£|¥|₹"

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+")

#: Requires separators or a country code, which keeps bare years out.
PHONE_RE = re.compile(
    r"(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{2,4}\)[\s.\-]?)?\d{3,4}[\s.\-]\d{3,4}(?:[\s.\-]\d{2,4})?"
)

MONEY_RE = re.compile(
    rf"(?:{CURRENCY_SYMBOLS})\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:thousand|million|billion|trillion|k|m|bn))?"
    rf"|\d[\d,]*(?:\.\d+)?\s?(?:{CURRENCY_SYMBOLS})",
    re.IGNORECASE,
)

DATE_RE = re.compile(
    rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b"
    rf"|\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b"
    rf"|\b(?:{MONTH_NAMES})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b"
    rf"|\b\d{{1,2}}\s+(?:{MONTH_NAMES})\.?\s+\d{{4}}\b",
    re.IGNORECASE,
)

PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%")

IDENTIFIER_RE = re.compile(
    r"\b(?:INV|PO|SO|REF|ORD|TXN|DOC|ACCT|ACC|CASE|TICKET|PROJ)[-\s]?\d{3,}[A-Za-z0-9\-]*\b",
    re.IGNORECASE,
)


def _unique(matches: list[str], limit: int = MAX_VALUES) -> list[str]:
    """De-duplicate while preserving first-seen order, capped at ``limit``."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in matches:
        value = " ".join(raw.split())
        if not value or value.lower() in seen:
            continue
        seen.add(value.lower())
        result.append(value)
        if len(result) >= limit:
            break
    return result


class EntityExtractor(Extractor):
    """Extract contacts, references, money, dates, and percentages."""

    name = "entities"

    def extract(self, document: Document) -> ExtractionResult | None:
        text = document.text
        if not text.strip():
            return None

        emails = EMAIL_RE.findall(text)
        urls = URL_RE.findall(text)
        phones = [p for p in PHONE_RE.findall(text) if not DATE_RE.fullmatch(p.strip())]
        money = MONEY_RE.findall(text)
        dates = DATE_RE.findall(text)
        percents = PERCENT_RE.findall(text)
        identifiers = IDENTIFIER_RE.findall(text)

        # Lists hold samples; counts describe the full document.
        fields = {
            "emails": _unique(emails),
            "email_count": len(emails),
            "urls": _unique(urls),
            "url_count": len(urls),
            "phone_numbers": _unique(phones),
            "phone_count": len(phones),
            "money_amounts": _unique(money),
            "money_count": len(money),
            "dates": _unique(dates),
            "date_count": len(dates),
            "percentages": _unique(percents),
            "percentage_count": len(percents),
            "identifiers": _unique(identifiers),
            "identifier_count": len(identifiers),
            "has_contact_info": bool(emails or phones),
        }
        return ExtractionResult(extractor=self.name, fields=fields, confidence=0.8)
