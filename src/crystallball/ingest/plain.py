"""Loaders for plain text, delimited text, and JSON."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from ..errors import LoadError
from ..models import (
    BLOCK_HEADING,
    BLOCK_PARAGRAPH,
    BLOCK_SHEET_ROW,
    Document,
    SourceRef,
    TextBlock,
)

#: Encodings tried in order when reading a text file.
ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1")


def read_text(path: Path) -> str:
    """Read a text file, tolerating the encodings that show up in practice.

    ``latin-1`` is last and never fails, so this function only raises for
    unreadable files, not for unusual byte sequences.
    """
    raw = path.read_bytes()
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    raise LoadError(f"could not decode {path} with any of {', '.join(ENCODINGS)}")


def split_paragraphs(text: str, *, start_index: int = 1) -> list[TextBlock]:
    """Split text on blank lines into paragraph blocks with page-like locators."""
    blocks: list[TextBlock] = []
    for offset, chunk in enumerate(text.split("\n\n")):
        cleaned = chunk.strip()
        if cleaned:
            blocks.append(
                TextBlock(
                    kind=BLOCK_PARAGRAPH,
                    text=cleaned,
                    locator=f"p.{start_index + offset}",
                )
            )
    return blocks


class PlainTextLoader:
    """Loader for ``.txt``, ``.log``, ``.rst``, and similar plain text."""

    name = "plain-text"
    media_types = ("text/plain", "text/x-rst", "application/xml")

    def load(self, path: Path, source: SourceRef) -> Document:
        text = read_text(path)
        blocks = split_paragraphs(text)
        return Document(
            source=source,
            text=text,
            blocks=blocks,
            metadata={
                "encoding_hint": "text",
                "line_count": text.count("\n") + (1 if text else 0),
                "paragraph_count": len(blocks),
            },
        )


class MarkdownLoader:
    """Loader for Markdown that recognises ATX headings as structure."""

    name = "markdown"
    media_types = ("text/markdown",)

    def load(self, path: Path, source: SourceRef) -> Document:
        text = read_text(path)
        blocks: list[TextBlock] = []
        buffer: list[str] = []
        index = 0

        def flush() -> None:
            nonlocal buffer, index
            if buffer:
                index += 1
                blocks.append(
                    TextBlock(
                        kind=BLOCK_PARAGRAPH,
                        text="\n".join(buffer).strip(),
                        locator=f"p.{index}",
                    )
                )
                buffer = []

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                marks = len(stripped) - len(stripped.lstrip("#"))
                title = stripped[marks:].strip()
                if title and marks <= 6:
                    flush()
                    blocks.append(
                        TextBlock(
                            kind=BLOCK_HEADING,
                            text=title,
                            locator=f"h{marks}",
                            level=marks,
                        )
                    )
                    continue
            if not stripped:
                flush()
            else:
                buffer.append(line)
        flush()

        return Document(
            source=source,
            text=text,
            blocks=blocks,
            metadata={
                "heading_count": sum(1 for b in blocks if b.kind == BLOCK_HEADING),
                "paragraph_count": sum(1 for b in blocks if b.kind == BLOCK_PARAGRAPH),
            },
        )


class CsvLoader:
    """Loader for delimited text.

    Each data row becomes a ``table_row`` block located as ``row:N`` so values
    extracted from it stay traceable.
    """

    name = "delimited"
    media_types = ("text/csv", "text/tab-separated-values")

    def __init__(self, *, max_rows: int = 50_000) -> None:
        self.max_rows = max_rows

    def load(self, path: Path, source: SourceRef) -> Document:
        text = read_text(path)
        delimiter = "\t" if source.media_type.endswith("tab-separated-values") else ","
        try:
            reader = csv.reader(io.StringIO(text), delimiter=delimiter)
            rows = []
            for i, row in enumerate(reader):
                if i >= self.max_rows:
                    break
                rows.append(row)
        except csv.Error as exc:
            raise LoadError(f"could not parse delimited file {path}: {exc}") from exc

        header = rows[0] if rows else []
        blocks: list[TextBlock] = []
        for row_index, row in enumerate(rows, start=1):
            blocks.append(
                TextBlock(
                    kind=BLOCK_SHEET_ROW,
                    text=delimiter.join(row),
                    locator=f"row:{row_index}",
                )
            )
        return Document(
            source=source,
            text=text,
            blocks=blocks,
            metadata={
                "columns": header,
                "column_count": len(header),
                "row_count": max(len(rows) - 1, 0),
                "truncated": len(rows) >= self.max_rows,
            },
        )


class JsonLoader:
    """Loader for JSON documents.

    JSON is already structured, so this loader's job is to describe the shape
    (top-level keys, nesting depth, record count) rather than to parse meaning.
    """

    name = "json"
    media_types = ("application/json",)

    def load(self, path: Path, source: SourceRef) -> Document:
        text = read_text(path)
        try:
            payload: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LoadError(f"{path} is not valid JSON: {exc}") from exc

        if isinstance(payload, list):
            top_keys: list[str] = sorted(
                {k for item in payload if isinstance(item, dict) for k in item}
            )
            record_count = len(payload)
            root_type = "array"
        elif isinstance(payload, dict):
            top_keys = sorted(payload)
            record_count = 1
            root_type = "object"
        else:
            top_keys = []
            record_count = 1
            root_type = type(payload).__name__

        blocks = [
            TextBlock(
                kind=BLOCK_PARAGRAPH,
                text=json.dumps(payload, indent=2, ensure_ascii=False)[:100_000],
                locator="$",
            )
        ]
        return Document(
            source=source,
            text=text,
            blocks=blocks,
            metadata={
                "root_type": root_type,
                "top_level_keys": top_keys,
                "record_count": record_count,
                "max_depth": _depth(payload),
            },
        )


def _depth(value: Any, current: int = 0) -> int:
    """Maximum nesting depth of a JSON-like structure."""
    if isinstance(value, dict) and value:
        return max(_depth(v, current + 1) for v in value.values())
    if isinstance(value, list) and value:
        return max(_depth(v, current + 1) for v in value)
    return current
