"""Ingestion: turn files on disk into :class:`~crystallball.models.Document`.

Importing this package registers the built-in loaders, which makes
``crystallball.ingest.load_document`` usable without further setup.
"""

from __future__ import annotations

from .base import (
    LOADERS,
    MEDIA_TYPES,
    SKIP_DIRS,
    Loader,
    detect_media_type,
    discover_sources,
    iter_source_files,
    load_document,
    loader_for,
    register_loader,
    supported_media_types,
)
from .image import ImageLoader
from .markup import HtmlLoader
from .office import DocxLoader, PptxLoader, XlsxLoader
from .pdf import PdfLoader
from .plain import CsvLoader, JsonLoader, MarkdownLoader, PlainTextLoader

#: Built-in loaders, registered in the order listed.
DEFAULT_LOADERS: tuple[Loader, ...] = (
    PlainTextLoader(),
    MarkdownLoader(),
    CsvLoader(),
    JsonLoader(),
    HtmlLoader(),
    DocxLoader(),
    PptxLoader(),
    XlsxLoader(),
    ImageLoader(),
    PdfLoader(),
)


def register_default_loaders(*, overwrite: bool = False) -> None:
    """Register every built-in loader. Idempotent when ``overwrite`` is False."""
    for loader in DEFAULT_LOADERS:
        register_loader(loader, overwrite=overwrite)


register_default_loaders()

__all__ = [
    "LOADERS",
    "MEDIA_TYPES",
    "SKIP_DIRS",
    "DEFAULT_LOADERS",
    "Loader",
    "detect_media_type",
    "discover_sources",
    "iter_source_files",
    "load_document",
    "loader_for",
    "register_default_loaders",
    "register_loader",
    "supported_media_types",
    "PlainTextLoader",
    "MarkdownLoader",
    "CsvLoader",
    "JsonLoader",
    "HtmlLoader",
    "DocxLoader",
    "PptxLoader",
    "XlsxLoader",
    "ImageLoader",
    "PdfLoader",
]
