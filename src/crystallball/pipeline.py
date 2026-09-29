"""Pipeline orchestration: sources in, a validated data product out.

The run is deliberately failure-tolerant. One unreadable file or one extractor
that raises does not abort the product; it is recorded in the manifest's
``failures`` block and surfaced in the quality report. Silent partial success
is the failure mode this design exists to prevent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contract import ProductContract
from .errors import CrystallballError, PublishError
from .extract.base import Extractor, apply_extractors, build_extractors
from .ingest.base import discover_sources, load_document
from .models import ENVELOPE_COLUMNS, Document, Record, make_record_id
from .publish.manifest import build_manifest, write_manifest
from .publish.writers import SUPPORTED_FORMATS, write_rows
from .quality.checks import QualityReport, validate_records
from .version import __version__

#: Formats written when the caller does not choose any.
DEFAULT_FORMATS: tuple[str, ...] = ("jsonl",)


@dataclass(slots=True)
class PipelineOptions:
    """Configuration for one pipeline run."""

    out_dir: Path
    formats: tuple[str, ...] = DEFAULT_FORMATS
    extractor_names: tuple[str, ...] | None = None
    recursive: bool = True
    strict: bool = False
    include_envelope: bool = True
    low_confidence_threshold: float = 0.5
    write_contract: bool = True
    write_quality: bool = True

    def __post_init__(self) -> None:
        self.out_dir = Path(self.out_dir)
        unknown = [f for f in self.formats if f not in SUPPORTED_FORMATS]
        if unknown:
            raise PublishError(
                f"unsupported format(s) {', '.join(unknown)}; "
                f"supported: {', '.join(SUPPORTED_FORMATS)}"
            )
        if not self.formats:
            raise PublishError("at least one output format is required")


@dataclass(slots=True)
class PipelineResult:
    """Everything a run produced, including its diagnostics."""

    product_dir: Path
    product_name: str
    records: list[Record] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    quality: QualityReport | None = None
    manifest: dict[str, Any] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)
    load_failures: list[dict[str, Any]] = field(default_factory=list)
    extract_failures: list[dict[str, Any]] = field(default_factory=list)
    sources_considered: int = 0

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def passed(self) -> bool:
        return self.quality.passed if self.quality else True

    def summary(self) -> dict[str, Any]:
        """Compact, JSON-serialisable run summary."""
        return {
            "product": self.product_name,
            "product_dir": str(self.product_dir),
            "sources_considered": self.sources_considered,
            "documents_loaded": self.document_count,
            "records": self.record_count,
            "load_failures": len(self.load_failures),
            "extract_failures": len(self.extract_failures),
            "quality_passed": self.passed,
            "errors": self.quality.error_count if self.quality else 0,
            "warnings": self.quality.warning_count if self.quality else 0,
            "files": [str(p) for p in self.files],
        }


def _record_columns(
    contract: ProductContract, *, include_envelope: bool
) -> list[str]:
    columns = list(contract.field_names)
    if include_envelope:
        columns.extend(ENVELOPE_COLUMNS)
    return columns


def run_pipeline(
    sources: Sequence[str | Path],
    contract: ProductContract,
    options: PipelineOptions,
) -> PipelineResult:
    """Run extraction over ``sources`` and publish a data product.

    Args:
        sources: files or directories to ingest.
        contract: the published interface records must satisfy.
        options: run configuration, including the output directory.

    Returns:
        A :class:`PipelineResult`. When ``options.strict`` is set and validation
        fails, artifacts are still written (so the failure is diagnosable) and
        a :class:`~crystallball.errors.PublishError` is then raised.
    """
    started_at = datetime.now(timezone.utc)
    product_dir = options.out_dir / contract.name
    result = PipelineResult(product_dir=product_dir, product_name=contract.name)

    extractors: list[Extractor] = build_extractors(options.extractor_names)
    files = discover_sources(sources, recursive=options.recursive)
    result.sources_considered = len(files)

    declared = set(contract.field_names)
    dropped_counts: dict[str, int] = {}

    for path in files:
        try:
            document = load_document(path)
        except (CrystallballError, OSError) as exc:
            result.load_failures.append(
                {"path": str(path), "error": f"{type(exc).__name__}: {exc}"}
            )
            continue

        result.documents.append(document)

        try:
            fields, contributors, confidence = apply_extractors(document, extractors)
        except Exception as exc:  # noqa: BLE001 - isolate one bad document
            result.extract_failures.append(
                {"path": str(path), "error": f"{type(exc).__name__}: {exc}"}
            )
            continue

        # The contract is the gate: only declared fields ship.
        selected = {name: fields.get(name) for name in contract.field_names}
        for name in fields:
            if name not in declared:
                dropped_counts[name] = dropped_counts.get(name, 0) + 1

        result.records.append(
            Record(
                product=contract.name,
                record_id=make_record_id(contract.name, document.source.sha256),
                fields=selected,
                source_uri=document.source.uri,
                source_sha256=document.source.sha256,
                source_media_type=document.source.media_type,
                extractors=contributors,
                confidence=confidence,
            )
        )

    quality = validate_records(
        result.records,
        contract,
        dropped_fields=dropped_counts,
        low_confidence_threshold=options.low_confidence_threshold,
    )
    result.quality = quality

    # -- publish ---------------------------------------------------------
    columns = _record_columns(contract, include_envelope=options.include_envelope)
    rows = [record.to_row() for record in result.records]
    if not options.include_envelope:
        rows = [{key: row.get(key) for key in contract.field_names} for row in rows]

    written: list[Path] = []
    for fmt in options.formats:
        written.append(
            write_rows(rows, product_dir, fmt, stem="records", columns=columns)
        )

    if options.write_contract:
        written.append(contract.to_json(product_dir / "contract.json"))
    if options.write_quality:
        import json

        quality_path = product_dir / "quality.json"
        quality_path.write_text(
            json.dumps(quality.to_dict(), indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        written.append(quality_path)

    finished_at = datetime.now(timezone.utc)
    manifest = build_manifest(
        contract,
        result.documents,
        result.records,
        quality,
        written,
        extractors=[e.name for e in extractors],
        formats=list(options.formats),
        tool_version=__version__,
        source_paths=[str(s) for s in sources],
        started_at=started_at,
        finished_at=finished_at,
        load_failures=result.load_failures,
        extract_failures=result.extract_failures,
    )
    result.manifest = manifest
    written.append(write_manifest(manifest, product_dir))
    result.files = written

    if options.strict and not quality.passed:
        first = quality.errors[0] if quality.errors else None
        detail = f" First error: {first.message}" if first else ""
        raise PublishError(
            f"product {contract.name!r} failed validation with "
            f"{quality.error_count} error(s); artifacts were written to "
            f"{product_dir} for inspection.{detail}"
        )

    return result


def load_and_run(
    sources: Sequence[str | Path],
    contract_path: str | Path,
    options: PipelineOptions,
) -> PipelineResult:
    """Convenience wrapper: read a contract from JSON, then run the pipeline."""
    return run_pipeline(sources, ProductContract.from_json(contract_path), options)


def rows_from_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL product file back into row dicts."""
    import json

    rows: list[dict[str, Any]] = []
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    rows.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    raise PublishError(
                        f"{path}:{line_number} is not valid JSON: {exc}"
                    ) from exc
    except FileNotFoundError as exc:
        raise PublishError(f"records file not found: {path}") from exc
    return rows


def records_from_rows(
    rows: Sequence[Mapping[str, Any]], contract: ProductContract
) -> list[Record]:
    """Rebuild :class:`Record` objects from published rows.

    Envelope columns are recognised and restored to their dedicated attributes,
    so a published product can be re-validated without the original documents.
    """
    envelope = set(ENVELOPE_COLUMNS)
    records: list[Record] = []
    for row in rows:
        fields = {k: v for k, v in row.items() if k not in envelope}
        records.append(
            Record(
                product=contract.name,
                record_id=str(row.get("record_id", "")),
                fields=fields,
                source_uri=str(row.get("source_uri", "")),
                source_sha256=str(row.get("source_sha256", "")),
                source_media_type=str(row.get("source_media_type", "")),
                extractors=list(row.get("extractors", []) or []),
                confidence=float(row.get("confidence", 1.0) or 1.0),
            )
        )
    return records
