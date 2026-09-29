"""Quality checks applied to records before anything is published.

Validation is deliberately two-way. Rows are checked against the contract, and
the contract is checked against reality: fields that are declared but never
populated are reported, because a silent all-null column is the most common way
a data product rots without anyone noticing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..contract import ProductContract, type_name
from ..models import Record

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


@dataclass(frozen=True, slots=True)
class Issue:
    """One validation finding."""

    code: str
    severity: str
    message: str
    record_id: str | None = None
    field: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {"code": self.code, "severity": self.severity, "message": self.message}
        if self.record_id:
            payload["record_id"] = self.record_id
        if self.field:
            payload["field"] = self.field
        return payload


@dataclass(slots=True)
class FieldProfile:
    """Per-field statistics gathered while validating."""

    name: str
    non_null: int = 0
    null: int = 0
    distinct: int = 0
    examples: list[str] = field(default_factory=list)

    @property
    def fill_rate(self) -> float:
        total = self.non_null + self.null
        return round(self.non_null / total, 4) if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "non_null": self.non_null,
            "null": self.null,
            "distinct": self.distinct,
            "fill_rate": self.fill_rate,
            "examples": self.examples,
        }


@dataclass(slots=True)
class QualityReport:
    """The outcome of validating one product's records."""

    product: str
    record_count: int
    issues: list[Issue] = field(default_factory=list)
    profiles: list[FieldProfile] = field(default_factory=list)
    dropped_fields: dict[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == SEVERITY_ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == SEVERITY_WARNING]

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def passed(self) -> bool:
        """True when no error-severity issue was found."""
        return self.error_count == 0

    def profile(self, name: str) -> FieldProfile | None:
        for item in self.profiles:
            if item.name == name:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "record_count": self.record_count,
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [i.to_dict() for i in self.issues],
            "fields": [p.to_dict() for p in self.profiles],
            "dropped_fields": self.dropped_fields,
        }


def _hashable(value: Any) -> str:
    """Represent any JSON-ish value as a hashable string."""
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, sort_keys=True, default=str)
    return f"{type(value).__name__}:{value}"


def profile_records(
    records: Sequence[Record], contract: ProductContract
) -> list[FieldProfile]:
    """Compute per-field fill rates and example values."""
    profiles: list[FieldProfile] = []
    for spec in contract.fields:
        seen: set[str] = set()
        examples: list[str] = []
        non_null = 0
        for record in records:
            value = record.fields.get(spec.name)
            if value is None or value == "" or value == []:
                continue
            non_null += 1
            key = _hashable(value)
            if key not in seen:
                seen.add(key)
                if len(examples) < 3:
                    examples.append(str(value)[:80])
        profiles.append(
            FieldProfile(
                name=spec.name,
                non_null=non_null,
                null=len(records) - non_null,
                distinct=len(seen),
                examples=examples,
            )
        )
    return profiles


def validate_records(
    records: Sequence[Record],
    contract: ProductContract,
    *,
    dropped_fields: dict[str, int] | None = None,
    low_confidence_threshold: float = 0.5,
    max_reported: int = 20,
) -> QualityReport:
    """Validate records against ``contract`` and profile the result.

    Only the first ``max_reported`` issues of each code are recorded, so a badly
    broken run reports a readable summary instead of thousands of lines.
    """
    report = QualityReport(product=contract.name, record_count=len(records))
    if dropped_fields:
        report.dropped_fields = dict(sorted(dropped_fields.items()))

    if not records:
        report.issues.append(
            Issue(
                code="empty_product",
                severity=SEVERITY_WARNING,
                message="no records were produced; check that sources contain text",
            )
        )
        report.profiles = profile_records(records, contract)
        return report

    declared = set(contract.field_names)
    seen_keys: dict[tuple, str] = {}
    per_code: dict[str, int] = {}

    def add(issue: Issue) -> None:
        count = per_code.get(issue.code, 0)
        if count < max_reported:
            report.issues.append(issue)
        per_code[issue.code] = count + 1

    for record in records:
        # Envelope columns participate in key checks, so validate the row as it
        # will actually be published rather than the extracted fields alone.
        row = record.to_row()

        # Contract conformance.
        for spec in contract.fields:
            value = record.fields.get(spec.name)
            if spec.required and (value is None or value == ""):
                add(
                    Issue(
                        code="missing_required_field",
                        severity=SEVERITY_ERROR,
                        message=f"required field {spec.name!r} is missing or empty",
                        record_id=record.record_id,
                        field=spec.name,
                    )
                )
                continue
            ok, reason = spec.accepts(value)
            if not ok:
                add(
                    Issue(
                        code="type_mismatch",
                        severity=SEVERITY_ERROR,
                        message=(
                            f"field {spec.name!r}: {reason} "
                            f"(got {type_name(value)})"
                        ),
                        record_id=record.record_id,
                        field=spec.name,
                    )
                )

        # Undeclared fields should already be filtered out upstream; flag leaks.
        for name in record.fields:
            if name not in declared:
                add(
                    Issue(
                        code="undeclared_field",
                        severity=SEVERITY_WARNING,
                        message=f"field {name!r} is not declared in the contract",
                        record_id=record.record_id,
                        field=name,
                    )
                )

        # Primary key integrity.
        if contract.primary_key:
            key_values = tuple(row.get(k) for k in contract.primary_key)
            if any(v is None or v == "" for v in key_values):
                add(
                    Issue(
                        code="null_primary_key",
                        severity=SEVERITY_ERROR,
                        message=(
                            f"primary key {contract.primary_key} contains a null value"
                        ),
                        record_id=record.record_id,
                    )
                )
            elif key_values in seen_keys:
                add(
                    Issue(
                        code="duplicate_primary_key",
                        severity=SEVERITY_ERROR,
                        message=(
                            f"primary key {key_values} duplicates record "
                            f"{seen_keys[key_values]}"
                        ),
                        record_id=record.record_id,
                    )
                )
            else:
                seen_keys[key_values] = record.record_id

        if record.confidence < low_confidence_threshold:
            add(
                Issue(
                    code="low_confidence",
                    severity=SEVERITY_WARNING,
                    message=f"record confidence {record.confidence:.2f} is below threshold",
                    record_id=record.record_id,
                )
            )

    report.profiles = profile_records(records, contract)

    # Contract-side checks: declared but never populated.
    for profile in report.profiles:
        if profile.non_null == 0 and report.record_count:
            spec = contract.field(profile.name)
            severity = SEVERITY_ERROR if spec and spec.required else SEVERITY_INFO
            report.issues.append(
                Issue(
                    code="field_never_populated",
                    severity=severity,
                    message=(
                        f"field {profile.name!r} is null in all "
                        f"{report.record_count} records"
                    ),
                    field=profile.name,
                )
            )

    for name, count in report.dropped_fields.items():
        report.issues.append(
            Issue(
                code="field_dropped",
                severity=SEVERITY_INFO,
                message=(
                    f"extracted field {name!r} was dropped in {count} record(s) "
                    f"because the contract does not declare it"
                ),
                field=name,
            )
        )

    report.issues.sort(key=lambda i: (i.severity, i.code, i.record_id or ""))
    return report


def merge_reports(product: str, reports: Iterable[QualityReport]) -> QualityReport:
    """Combine several reports into one, keeping the first product name."""
    merged = QualityReport(product=product, record_count=0)
    for report in reports:
        merged.record_count += report.record_count
        merged.issues.extend(report.issues)
        merged.profiles.extend(report.profiles)
        for name, count in report.dropped_fields.items():
            merged.dropped_fields[name] = merged.dropped_fields.get(name, 0) + count
    return merged
