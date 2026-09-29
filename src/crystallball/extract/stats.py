"""Deterministic document statistics.

This is the baseline extractor: cheap, reproducible, and always runnable. Its
output is what makes a corpus queryable before any semantic extraction exists
— you can find the longest documents, the ones with tables, the scanned ones
with no text at all.
"""

from __future__ import annotations

import re

from ..models import (
    BLOCK_HEADING,
    BLOCK_SHEET_ROW,
    BLOCK_SLIDE,
    BLOCK_TABLE_ROW,
    Document,
    ExtractionResult,
)
from .base import Extractor

#: Word-like tokens, including internal apostrophes and hyphens.
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")

#: Sentence terminators followed by whitespace or end of string.
_SENTENCE_RE = re.compile(r"[.!?]+(?:\s|$)")

#: Average adult reading speed, words per minute.
WORDS_PER_MINUTE = 220


class DocumentStatsExtractor(Extractor):
    """Emit size, structure, and readability statistics for a document."""

    name = "document_stats"

    def extract(self, document: Document) -> ExtractionResult | None:
        words = _WORD_RE.findall(document.text)
        word_count = len(words)
        unique_words = {w.lower() for w in words}
        sentence_count = len(_SENTENCE_RE.findall(document.text)) or (
            1 if document.text.strip() else 0
        )

        heading_count = sum(1 for b in document.blocks if b.kind == BLOCK_HEADING)
        table_rows = sum(
            1 for b in document.blocks if b.kind == BLOCK_TABLE_ROW
        )
        sheet_rows = sum(1 for b in document.blocks if b.kind == BLOCK_SHEET_ROW)
        slide_blocks = sum(1 for b in document.blocks if b.kind == BLOCK_SLIDE)

        fields = {
            "title": document.title,
            "document_type": _document_type(document),
            "word_count": word_count,
            "char_count": len(document.text),
            "sentence_count": sentence_count,
            "paragraph_count": sum(
                1
                for b in document.blocks
                if b.kind not in (BLOCK_HEADING, BLOCK_TABLE_ROW, BLOCK_SHEET_ROW)
            ),
            "heading_count": heading_count,
            "table_row_count": table_rows,
            "sheet_row_count": sheet_rows,
            "slide_block_count": slide_blocks,
            "unique_word_count": len(unique_words),
            "lexical_diversity": (
                round(len(unique_words) / word_count, 4) if word_count else 0.0
            ),
            "avg_words_per_sentence": (
                round(word_count / sentence_count, 2) if sentence_count else 0.0
            ),
            "reading_time_minutes": round(word_count / WORDS_PER_MINUTE, 2),
            "has_tables": table_rows > 0 or sheet_rows > 0,
            "is_empty": word_count == 0,
        }
        return ExtractionResult(extractor=self.name, fields=fields, confidence=1.0)


def _document_type(document: Document) -> str:
    """Coarse content class derived from the media type and structure."""
    media_type = document.source.media_type
    if media_type == "text/markdown":
        return "markdown"
    if media_type == "text/html":
        return "html"
    if media_type == "application/pdf":
        return "pdf"
    if media_type.endswith("wordprocessingml.document"):
        return "docx"
    if media_type.endswith("presentationml.presentation"):
        return "pptx"
    if media_type.endswith("spreadsheetml.sheet"):
        return "xlsx"
    if media_type.startswith("image/"):
        return "image"
    if media_type == "application/json":
        return "json"
    if media_type.startswith("text/"):
        return "text"
    return "unknown"
