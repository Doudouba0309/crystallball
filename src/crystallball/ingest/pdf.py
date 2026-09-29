"""PDF loader backed by the optional ``pypdf`` dependency."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import LoadError
from ..models import BLOCK_PARAGRAPH, Document, SourceRef, TextBlock
from ._optional import require


class PdfLoader:
    """Loader for PDF files, one block per page.

    Text extraction quality depends on the PDF: scanned pages carry no text
    layer and yield empty pages. Those are reported via
    ``metadata['empty_pages']`` so a pipeline can route them to OCR instead of
    silently publishing blanks.
    """

    name = "pdf"
    media_types = ("application/pdf",)

    def load(self, path: Path, source: SourceRef) -> Document:
        pypdf = require("pypdf", "pdf", purpose="reading PDF files")
        try:
            reader = pypdf.PdfReader(str(path))
        except Exception as exc:  # noqa: BLE001 - pypdf raises varied types
            raise LoadError(f"could not open PDF {path}: {exc}") from exc

        blocks: list[TextBlock] = []
        empty_pages: list[int] = []

        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001 - per-page failures are non-fatal
                text = ""
                empty_pages.append(page_number)
                del exc
            cleaned = text.strip()
            if not cleaned:
                empty_pages.append(page_number)
                continue
            blocks.append(
                TextBlock(kind=BLOCK_PARAGRAPH, text=cleaned, locator=f"p.{page_number}")
            )

        page_count = len(reader.pages)
        return Document(
            source=source,
            text="\n\n".join(b.text for b in blocks),
            blocks=blocks,
            metadata={
                "page_count": page_count,
                "pages_with_text": page_count - len(empty_pages),
                "empty_pages": empty_pages[:100],
                "encrypted": bool(getattr(reader, "is_encrypted", False)),
                **_pdf_metadata(reader),
            },
        )


def _pdf_metadata(reader: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        info = reader.metadata
    except Exception:  # noqa: BLE001
        return result
    if not info:
        return result
    for key in ("/Title", "/Author", "/Subject", "/Creator", "/Producer"):
        value = info.get(key)
        if value:
            result[f"pdf_{key.lstrip('/').lower()}"] = str(value)
    return result
