"""Shared helper for loaders whose backing library is an optional extra."""

from __future__ import annotations

import importlib
from types import ModuleType

from ..errors import LoadError


def require(module: str, extra: str, *, purpose: str) -> ModuleType:
    """Import ``module`` or raise a LoadError naming the extra to install.

    Importing lazily keeps optional dependencies genuinely optional: the core
    package imports cleanly on a bare interpreter, and only a run that actually
    needs the format pays for it.
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise LoadError(
            f"{purpose} requires the {module!r} package, which is not installed. "
            f"Install it with: pip install 'crystallball[{extra}]'"
        ) from exc
