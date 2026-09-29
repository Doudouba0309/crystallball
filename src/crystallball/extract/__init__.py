"""Extraction: turn documents into structured fields.

Importing this package registers the built-in extractors. The LLM extractor is
intentionally *not* registered, because it needs a caller-supplied completion
function; construct and register one explicitly when you want it.
"""

from __future__ import annotations

from .base import (
    EXTRACTORS,
    Extractor,
    apply_extractors,
    available_extractors,
    build_extractors,
    register_extractor,
)
from .entities import EntityExtractor
from .keyvalue import KeyValueExtractor
from .llm import LlmExtractor, build_prompt, parse_json_response
from .stats import DocumentStatsExtractor

#: Built-in extractors, registered in order. Order is precedence: earlier
#: extractors win when two produce the same field.
DEFAULT_EXTRACTORS: tuple[Extractor, ...] = (
    DocumentStatsExtractor(),
    EntityExtractor(),
    KeyValueExtractor(),
)


def register_default_extractors(*, overwrite: bool = False) -> None:
    """Register every built-in extractor."""
    for extractor in DEFAULT_EXTRACTORS:
        register_extractor(extractor, overwrite=overwrite)


register_default_extractors()

__all__ = [
    "EXTRACTORS",
    "DEFAULT_EXTRACTORS",
    "Extractor",
    "apply_extractors",
    "available_extractors",
    "build_extractors",
    "register_default_extractors",
    "register_extractor",
    "DocumentStatsExtractor",
    "EntityExtractor",
    "KeyValueExtractor",
    "LlmExtractor",
    "build_prompt",
    "parse_json_response",
]
