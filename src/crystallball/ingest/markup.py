"""HTML loader built on the standard library.

Deliberately uses :mod:`html.parser` rather than a third-party parser so the
core install stays dependency-free. The goal is structural text recovery —
headings, paragraphs, list items, table rows — not full DOM fidelity.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from ..models import (
    BLOCK_HEADING,
    BLOCK_PARAGRAPH,
    BLOCK_TABLE_ROW,
    Document,
    SourceRef,
    TextBlock,
)
from .plain import read_text

#: Tags whose text content is never useful.
SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})

#: Block-level tags treated as paragraphs.
PARAGRAPH_TAGS = frozenset(
    {"p", "li", "dd", "dt", "blockquote", "figcaption", "pre", "summary"}
)

HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

VOID_TAGS = frozenset({"br", "hr", "img", "meta", "link", "input", "area", "base"})


class _HtmlStructureParser(HTMLParser):
    """Collects headings, paragraphs, table rows, links, and the title."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[TextBlock] = []
        self.links: list[str] = []
        self.page_title: str | None = None
        self._skip_depth = 0
        self._open: list[dict] = []
        self._stray: list[str] = []
        self._cells: list[str] | None = None
        self._cell_buffer: list[str] | None = None
        self._row_index = 0
        self._title_buffer: list[str] | None = None

    # -- helpers ---------------------------------------------------------
    def _emit(self, kind: str, text: str, locator: str, level: int | None = None) -> None:
        cleaned = " ".join(text.split())
        if cleaned:
            self.blocks.append(
                TextBlock(kind=kind, text=cleaned, locator=locator, level=level)
            )

    def _flush_stray(self) -> None:
        if self._stray:
            self._emit(BLOCK_PARAGRAPH, "".join(self._stray), "text")
            self._stray = []

    # -- parser callbacks ------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag == "a":
            href = dict(attrs).get("href")
            if href and href not in self.links:
                self.links.append(href)
        elif tag == "title":
            self._title_buffer = []
            return
        elif tag in HEADING_TAGS:
            self._flush_stray()
            self._open.append(
                {
                    "tag": tag,
                    "kind": BLOCK_HEADING,
                    "level": HEADING_TAGS[tag],
                    "locator": tag,
                    "buffer": [],
                }
            )
            return
        elif tag in PARAGRAPH_TAGS:
            self._flush_stray()
            self._open.append(
                {
                    "tag": tag,
                    "kind": BLOCK_PARAGRAPH,
                    "level": None,
                    "locator": tag,
                    "buffer": [],
                }
            )
            return
        elif tag == "tr":
            self._cells = []
        elif tag in ("td", "th") and self._cells is not None:
            self._cell_buffer = []
        elif tag == "br":
            if self._open:
                self._open[-1]["buffer"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return

        if tag == "title" and self._title_buffer is not None:
            title = " ".join("".join(self._title_buffer).split())
            self.page_title = title or None
            self._title_buffer = None
            return
        if tag in ("td", "th") and self._cells is not None and self._cell_buffer is not None:
            self._cells.append(" ".join("".join(self._cell_buffer).split()))
            self._cell_buffer = None
            return
        if tag == "tr" and self._cells is not None:
            self._row_index += 1
            self._emit(
                BLOCK_TABLE_ROW,
                " | ".join(c for c in self._cells if c),
                f"row:{self._row_index}",
            )
            self._cells = None
            return

        for position in range(len(self._open) - 1, -1, -1):
            entry = self._open[position]
            if entry["tag"] == tag:
                del self._open[position]
                self._emit(
                    entry["kind"],
                    "".join(entry["buffer"]),
                    entry["locator"],
                    entry["level"],
                )
                return

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        if self._title_buffer is not None:
            self._title_buffer.append(data)
            return
        if self._cell_buffer is not None:
            self._cell_buffer.append(data)
            return
        if self._open:
            self._open[-1]["buffer"].append(data)
        elif data.strip():
            self._stray.append(data)

    def close(self) -> None:  # noqa: D102 - inherited
        super().close()
        self._flush_stray()


class HtmlLoader:
    """Loader for ``.html``, ``.htm``, and ``.xhtml`` files."""

    name = "html"
    media_types = ("text/html", "application/xhtml+xml")

    def load(self, path: Path, source: SourceRef) -> Document:
        raw = read_text(path)
        parser = _HtmlStructureParser()
        parser.feed(raw)
        parser.close()

        text = "\n\n".join(block.text for block in parser.blocks)
        return Document(
            source=source,
            text=text,
            blocks=parser.blocks,
            metadata={
                "page_title": parser.page_title,
                "link_count": len(parser.links),
                "links": parser.links[:50],
                "heading_count": sum(1 for b in parser.blocks if b.kind == BLOCK_HEADING),
                "table_row_count": sum(
                    1 for b in parser.blocks if b.kind == BLOCK_TABLE_ROW
                ),
            },
        )
