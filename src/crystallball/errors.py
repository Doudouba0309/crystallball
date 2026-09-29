"""Exception hierarchy for crystallball.

Every failure raised by the library derives from :class:`CrystallballError`, so
callers can catch one type at the boundary of a pipeline run.
"""

from __future__ import annotations


class CrystallballError(Exception):
    """Base class for all crystallball errors."""


class UnsupportedMediaType(CrystallballError):
    """No loader is registered for the detected media type."""


class LoadError(CrystallballError):
    """A source could not be read into a :class:`~crystallball.models.Document`."""


class ExtractError(CrystallballError):
    """An extractor failed while processing a document."""


class ContractError(CrystallballError):
    """A product contract is malformed or internally inconsistent."""


class PublishError(CrystallballError):
    """A data product could not be written to its destination."""
