"""Core domain models.

The pipeline moves through four shapes, in order:

``SourceRef`` -> ``Document`` -> ``ExtractionResult`` -> ``Record``

A ``SourceRef`` is the immutable identity of an input artifact, a ``Document``
is its loaded unstructured content, an ``ExtractionResult`` is what one
extractor contributed, and a ``Record`` is the structured row that ships in a
data product.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Text kinds a loader may emit. Kept as plain strings so custom loaders can
#: introduce their own kinds without touching this module.
BLOCK_HEADING = "heading"
BLOCK_PARAGRAPH = "paragraph"
BLOCK_TABLE_ROW = "table_row"
BLOCK_SLIDE = "slide"
BLOCK_SHEET_ROW = "sheet_row"
BLOCK_METADATA = "metadata"


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class TextBlock:
    """A located unit of text inside a document.

    ``locator`` is a human-readable pointer back into the source (``p.4``,
    ``slide 2``, ``Sheet1!A7``) so downstream consumers can trace any extracted
    value to where it came from.
    """

    kind: str
    text: str
    locator: str
    level: int | None = None


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Immutable identity of one input artifact."""

    uri: str
    media_type: str
    size_bytes: int
    sha256: str

    @property
    def name(self) -> str:
        """Basename of the source, for display and logging."""
        return self.uri.rsplit("/", 1)[-1] or self.uri

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }

    @classmethod
    def from_path(cls, path: Path, media_type: str) -> SourceRef:
        """Build a reference by hashing ``path`` on disk."""
        data = path.read_bytes()
        return cls(
            uri=str(path),
            media_type=media_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )


@dataclass(slots=True)
class Document:
    """Unstructured content loaded from a single source."""

    source: SourceRef
    text: str
    blocks: list[TextBlock] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str | None:
        """First level-1 heading, or the first heading of any level."""
        fallback: str | None = None
        for block in self.blocks:
            if block.kind != BLOCK_HEADING:
                continue
            if block.level in (None, 1):
                return block.text
            fallback = fallback or block.text
        return fallback

    @property
    def char_count(self) -> int:
        return len(self.text)

    def blocks_of(self, kind: str) -> list[TextBlock]:
        """Return every block of ``kind``."""
        return [b for b in self.blocks if b.kind == kind]


@dataclass(slots=True)
class ExtractionResult:
    """Fields contributed by one extractor for one document."""

    extractor: str
    fields: dict[str, Any]
    confidence: float = 1.0


@dataclass(slots=True)
class Record:
    """A structured row destined for a data product."""

    product: str
    record_id: str
    fields: dict[str, Any]
    source_uri: str
    source_sha256: str
    source_media_type: str
    extractors: list[str] = field(default_factory=list)
    confidence: float = 1.0
    extracted_at: datetime = field(default_factory=utcnow)

    def to_row(self) -> dict[str, Any]:
        """Flatten to the published row shape.

        Envelope columns are written alongside the contract fields so every
        row stays traceable to the document it came from.
        """
        row: dict[str, Any] = dict(self.fields)
        row.update(
            {
                "record_id": self.record_id,
                "source_uri": self.source_uri,
                "source_sha256": self.source_sha256,
                "source_media_type": self.source_media_type,
                "extractors": sorted(self.extractors),
                "confidence": round(float(self.confidence), 4),
                "extracted_at": self.extracted_at.isoformat(),
            }
        )
        return row


#: Columns every data product carries regardless of its contract.
ENVELOPE_COLUMNS: tuple[str, ...] = (
    "record_id",
    "source_uri",
    "source_sha256",
    "source_media_type",
    "extractors",
    "confidence",
    "extracted_at",
)


def make_record_id(product: str, source_sha256: str) -> str:
    """Derive a stable record id from the product name and content hash.

    Re-running the pipeline over unchanged input therefore produces identical
    ids, which keeps published products idempotent and joinable across runs.
    """
    digest = hashlib.sha256(f"{product}:{source_sha256}".encode("utf-8")).hexdigest()
    return digest[:16]
