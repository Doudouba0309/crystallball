"""A tiny name -> object registry used for loaders and extractors.

Both plugins are discovered by name, so a caller can select behaviour from a
CLI flag or a config file without importing the implementing module.
"""

from __future__ import annotations

from typing import Generic, Iterator, TypeVar

from .errors import CrystallballError

T = TypeVar("T")


class Registry(Generic[T]):
    """An ordered, name-keyed collection with a descriptive error type."""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: dict[str, T] = {}

    def register(self, name: str, item: T, *, overwrite: bool = False) -> T:
        """Add ``item`` under ``name``."""
        if not name:
            raise CrystallballError(f"cannot register {self._kind} with an empty name")
        if name in self._items and not overwrite:
            raise CrystallballError(f"{self._kind} {name!r} is already registered")
        self._items[name] = item
        return item

    def get(self, name: str) -> T:
        """Return the item registered as ``name``."""
        try:
            return self._items[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._items)) or "<none>"
            raise CrystallballError(
                f"unknown {self._kind} {name!r}; available: {available}"
            ) from exc

    def maybe(self, name: str) -> T | None:
        """Return the item registered as ``name``, or ``None``."""
        return self._items.get(name)

    def names(self) -> tuple[str, ...]:
        """Registered names, sorted."""
        return tuple(sorted(self._items))

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def __iter__(self) -> Iterator[T]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)
