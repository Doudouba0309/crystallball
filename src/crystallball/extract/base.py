"""Extractor plumbing: the protocol, the registry, and selection helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from ..errors import CrystallballError
from ..models import Document, ExtractionResult
from ..registry import Registry


@runtime_checkable
class Extractor(Protocol):
    """Derives structured fields from one document.

    Returning ``None`` means "this document is out of scope for me", which is
    different from returning an empty field mapping.
    """

    name: str

    def extract(self, document: Document) -> ExtractionResult | None:
        """Return fields for ``document``, or ``None`` to abstain."""


#: Extractor name -> instance, in registration order.
EXTRACTORS: Registry[Extractor] = Registry("extractor")


def register_extractor(extractor: Extractor, *, overwrite: bool = False) -> Extractor:
    """Register ``extractor`` under its ``name``."""
    return EXTRACTORS.register(extractor.name, extractor, overwrite=overwrite)


def available_extractors() -> tuple[str, ...]:
    """Names of all registered extractors, sorted."""
    return EXTRACTORS.names()


def build_extractors(names: Iterable[str] | None = None) -> list[Extractor]:
    """Resolve extractor names into instances.

    ``None`` selects every registered extractor in registration order, which is
    the default pipeline behaviour.

    Raises:
        CrystallballError: if a requested name is not registered.
    """
    if names is None:
        return list(EXTRACTORS)
    selected: list[Extractor] = []
    for name in names:
        extractor = EXTRACTORS.maybe(name)
        if extractor is None:
            raise CrystallballError(
                f"unknown extractor {name!r}; available: "
                f"{', '.join(available_extractors()) or '<none>'}"
            )
        selected.append(extractor)
    return selected


def apply_extractors(
    document: Document, extractors: Sequence[Extractor]
) -> tuple[dict, list[str], float]:
    """Run ``extractors`` over ``document`` and merge their fields.

    Later extractors fill gaps but never overwrite an earlier extractor's
    non-empty value, so ordering is a deterministic way to express precedence.
    Confidence is the minimum across contributors: a record is only as
    trustworthy as its least reliable field source.

    Returns:
        ``(fields, contributing_extractor_names, confidence)``
    """
    fields: dict = {}
    contributors: list[str] = []
    confidences: list[float] = []

    for extractor in extractors:
        result = extractor.extract(document)
        if result is None:
            continue
        contributors.append(result.extractor)
        confidences.append(float(result.confidence))
        for key, value in result.fields.items():
            if value is None:
                continue
            if key not in fields or fields[key] in (None, "", [], {}):
                fields[key] = value

    confidence = min(confidences) if confidences else 1.0
    return fields, contributors, confidence
