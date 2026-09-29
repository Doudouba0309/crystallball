"""Data product contracts.

A contract is the public interface of a data product: the field names, their
types, which are required, and which columns identify a row. Other teams can
build against it, and the pipeline validates every record against it before
anything is published.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ContractError
from .models import ENVELOPE_COLUMNS

#: Supported field types. ``any`` opts a field out of type checking.
FIELD_TYPES: tuple[str, ...] = (
    "string",
    "integer",
    "number",
    "boolean",
    "array",
    "object",
    "any",
)


def value_matches_type(value: Any, field_type: str) -> bool:
    """Return whether ``value`` satisfies ``field_type``.

    ``None`` always passes here, because nullability is a separate concern
    handled by :class:`FieldSpec`.
    """
    if field_type == "any" or value is None:
        return True
    if field_type == "string":
        return isinstance(value, str)
    if field_type == "boolean":
        return isinstance(value, bool)
    if field_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if field_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field_type == "array":
        return isinstance(value, (list, tuple))
    if field_type == "object":
        return isinstance(value, Mapping)
    return False


def type_name(value: Any) -> str:
    """Human-readable type name used in validation messages."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Declaration of one column in a data product."""

    name: str
    type: str = "any"
    required: bool = False
    nullable: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ContractError("field name must be a non-empty string")
        if self.type not in FIELD_TYPES:
            raise ContractError(
                f"field {self.name!r} has unknown type {self.type!r}; "
                f"expected one of {', '.join(FIELD_TYPES)}"
            )

    def accepts(self, value: Any) -> tuple[bool, str]:
        """Check one value, returning ``(ok, reason)``."""
        if value is None:
            if not self.nullable:
                return False, "null value in non-nullable field"
            return True, ""
        if not value_matches_type(value, self.type):
            return False, f"expected {self.type}, got {type_name(value)}"
        return True, ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "nullable": self.nullable,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FieldSpec:
        try:
            name = str(data["name"])
        except KeyError as exc:
            raise ContractError("field entry is missing 'name'") from exc
        return cls(
            name=name,
            type=str(data.get("type", "any")),
            required=bool(data.get("required", False)),
            nullable=bool(data.get("nullable", True)),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True, slots=True)
class ProductContract:
    """The published interface of a data product."""

    name: str
    version: str = "0.1.0"
    fields: tuple[FieldSpec, ...] = ()
    primary_key: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ContractError("contract name must be a non-empty string")
        seen: set[str] = set()
        for spec in self.fields:
            if spec.name in seen:
                raise ContractError(f"duplicate field {spec.name!r} in contract {self.name!r}")
            seen.add(spec.name)
        for key in self.primary_key:
            # Envelope columns are always present, so they are valid keys even
            # though extractors never produce them and they are not declared.
            if key not in seen and key not in ENVELOPE_COLUMNS:
                raise ContractError(
                    f"primary key column {key!r} is neither a declared field nor "
                    f"an envelope column in contract {self.name!r}"
                )

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.fields)

    def field(self, name: str) -> FieldSpec | None:
        """Look up a field spec by name."""
        for spec in self.fields:
            if spec.name == name:
                return spec
        return None

    @property
    def required_fields(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.fields if spec.required)

    def schema_hash(self) -> str:
        """Stable hash of the contract shape, used for change detection."""
        import hashlib

        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "primary_key": list(self.primary_key),
            "fields": [spec.to_dict() for spec in self.fields],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProductContract:
        """Build a contract from parsed JSON/YAML-equivalent data."""
        if not isinstance(data, Mapping):
            raise ContractError("contract must be a mapping")
        raw_fields = data.get("fields", [])
        if not isinstance(raw_fields, Sequence) or isinstance(raw_fields, (str, bytes)):
            raise ContractError("'fields' must be a list")
        return cls(
            name=str(data.get("name", "")),
            version=str(data.get("version", "0.1.0")),
            description=str(data.get("description", "")),
            fields=tuple(FieldSpec.from_dict(f) for f in raw_fields),
            primary_key=tuple(str(k) for k in data.get("primary_key", []) or ()),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> ProductContract:
        """Load a contract from a JSON file."""
        p = Path(path)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ContractError(f"contract file not found: {p}") from exc
        except json.JSONDecodeError as exc:
            raise ContractError(f"contract file {p} is not valid JSON: {exc}") from exc
        return cls.from_dict(raw)

    def to_json(self, path: str | Path) -> Path:
        """Write the contract to a JSON file and return the path."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return p


def contract_from_field_names(
    name: str,
    field_names: Iterable[str],
    *,
    version: str = "0.1.0",
    primary_key: Iterable[str] = (),
) -> ProductContract:
    """Convenience builder that infers nothing and marks all fields optional.

    Useful for exploration; prefer an explicit contract for anything published.
    """
    return ProductContract(
        name=name,
        version=version,
        fields=tuple(FieldSpec(name=f, type="any") for f in field_names),
        primary_key=tuple(primary_key),
    )
