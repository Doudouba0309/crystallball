"""Label/value extraction from document text.

Business documents are full of ``Invoice Number: INV-2024-001`` lines. This
extractor turns those into fields named after their labels. Because the labels
are open-ended, downstream governance matters: the pipeline only publishes
fields the product contract declares, so this extractor is a discovery aid
first and a product input second.
"""

from __future__ import annotations

import re

from ..models import Document, ExtractionResult
from .base import Extractor

#: ``Label: value`` or ``Label = value`` at the start of a line.
PAIR_RE = re.compile(
    r"^[ \t]*([A-Za-z][A-Za-z0-9 _\-/&.]{1,58}?)[ \t]*[:=][ \t]*(\S[^\n]{0,200}?)[ \t]*$",
    re.MULTILINE,
)

#: Labels that are almost always noise rather than real business fields.
STOP_LABELS = frozenset(
    {
        "http",
        "https",
        "note",
        "notes",
        "example",
        "e.g",
        "i.e",
        "see",
        "figure",
        "table",
        "page",
    }
)

MAX_PAIRS = 40
MAX_LABEL_WORDS = 6


def normalise_label(label: str) -> str:
    """Convert a human label into a snake_case field name.

    >>> normalise_label("Invoice Number")
    'invoice_number'
    """
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", label.strip().lower())
    return re.sub(r"_+", "_", cleaned).strip("_")


class KeyValueExtractor(Extractor):
    """Extract ``label: value`` pairs as ``kv_<label>`` fields."""

    name = "key_value"

    def extract(self, document: Document) -> ExtractionResult | None:
        text = document.text
        if not text.strip():
            return None

        fields: dict = {}
        labels: list[str] = []

        for label, value in PAIR_RE.findall(text):
            label = label.strip()
            if not label or len(label.split()) > MAX_LABEL_WORDS:
                continue
            key = normalise_label(label)
            if not key or key in STOP_LABELS:
                continue
            if key in fields:
                continue
            if len(fields) >= MAX_PAIRS:
                break
            fields[f"kv_{key}"] = value.strip()
            labels.append(key)

        if not labels:
            return None

        fields["key_value_labels"] = labels
        fields["key_value_count"] = len(labels)
        return ExtractionResult(extractor=self.name, fields=fields, confidence=0.7)
