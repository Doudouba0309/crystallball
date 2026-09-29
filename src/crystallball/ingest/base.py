"""Loader plumbing: media-type detection, the loader registry, and discovery."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..errors import UnsupportedMediaType
from ..models import Document, SourceRef
from ..registry import Registry

#: File extension -> IANA media type.
MEDIA_TYPES: dict[str, str] = {
    # Plain text family
    ".txt": "text/plain",
    ".text": "text/plain",
    ".log": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".rst": "text/x-rst",
    # Delimited and structured text
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    # Markup
    ".html": "text/html",
    ".htm": "text/html",
    ".xhtml": "application/xhtml+xml",
    ".xml": "application/xml",
    # Office Open XML
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    # Documents and images
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

#: Directories that never contain source material worth ingesting.
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "node_modules",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".pip-cache",
        ".idea",
        ".vscode",
        "dist",
        "build",
        ".tox",
        ".eggs",
    }
)


@runtime_checkable
class Loader(Protocol):
    """Turns a file on disk into a :class:`~crystallball.models.Document`."""

    name: str
    media_types: tuple[str, ...]

    def load(self, path: Path, source: SourceRef) -> Document:
        """Read ``path`` and return its loaded content."""


#: Media type (or ``type/*`` wildcard) -> loader instance.
LOADERS: Registry[Loader] = Registry("loader")

#: Wildcard registrations, checked when no exact media type matches.
_WILDCARDS: dict[str, Loader] = {}


def detect_media_type(path: Path) -> str:
    """Return the media type for ``path`` based on its extension.

    Unknown extensions fall back to a binary blob type rather than raising, so
    discovery can report on them and a custom loader can still claim them.
    """
    return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def register_loader(loader: Loader, *, overwrite: bool = False) -> Loader:
    """Register ``loader`` for every media type it declares.

    A media type ending in ``/*`` is stored as a wildcard, which lets one
    loader claim a whole family such as ``image/*``.
    """
    for media_type in loader.media_types:
        if media_type.endswith("/*"):
            prefix = media_type[:-1]
            if prefix in _WILDCARDS and not overwrite:
                raise UnsupportedMediaType(
                    f"a loader is already registered for {media_type!r}"
                )
            _WILDCARDS[prefix] = loader
        else:
            LOADERS.register(media_type, loader, overwrite=overwrite)
    return loader


def loader_for(media_type: str) -> Loader | None:
    """Return the loader for ``media_type``, trying wildcards as a fallback."""
    exact = LOADERS.maybe(media_type)
    if exact is not None:
        return exact
    family = media_type.split("/", 1)[0] + "/"
    return _WILDCARDS.get(family)


def supported_media_types() -> tuple[str, ...]:
    """Media types with a concrete loader registered, sorted."""
    return LOADERS.names()


def load_document(path: Path, *, media_type: str | None = None) -> Document:
    """Load one file into a :class:`Document`.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        UnsupportedMediaType: if no loader claims the detected media type.
    """
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"not a file: {resolved}")
    detected = media_type or detect_media_type(resolved)
    loader = loader_for(detected)
    if loader is None:
        raise UnsupportedMediaType(
            f"no loader registered for {detected!r} ({resolved.name}); "
            f"supported: {', '.join(supported_media_types())}"
        )
    source = SourceRef.from_path(resolved, detected)
    return loader.load(resolved, source)


def iter_source_files(
    paths: Iterable[str | Path],
    *,
    recursive: bool = True,
    skip_hidden: bool = True,
) -> Iterator[Path]:
    """Yield candidate source files from files and directories.

    Directories are walked in sorted order for deterministic output, skipping
    :data:`SKIP_DIRS` and (optionally) dot-files.
    """
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            for candidate in sorted(path.glob(pattern)):
                if not candidate.is_file():
                    continue
                if any(part in SKIP_DIRS for part in candidate.parts):
                    continue
                if skip_hidden and candidate.name.startswith("."):
                    continue
                yield candidate
        elif path.is_file():
            yield path


def discover_sources(
    paths: Iterable[str | Path],
    *,
    recursive: bool = True,
    skip_hidden: bool = True,
) -> list[Path]:
    """List the files a pipeline run would ingest, without reading them."""
    return list(
        iter_source_files(paths, recursive=recursive, skip_hidden=skip_hidden)
    )
