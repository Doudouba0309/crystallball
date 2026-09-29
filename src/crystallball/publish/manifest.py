"""Product manifest construction.

The manifest is the contract's companion: it records what was published, from
which inputs, with which extractors, and how the result validated. A consumer
can read the manifest alone to know whether a product is fit to use.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..contract import ProductContract
from ..errors import PublishError
from ..models import Document, Record
from ..quality.checks import QualityReport
from .writers import file_fingerprint

#: Bumped when the manifest layout changes in a breaking way.
MANIFEST_VERSION = 1

#: Issue detail retained in the manifest; the full set lives in quality.json.
MAX_ISSUES_IN_MANIFEST = 50


def build_manifest(
    contract: ProductContract,
    documents: Sequence[Document],
    records: Sequence[Record],
    quality: QualityReport,
    files: Sequence[Path],
    *,
    extractors: Sequence[str],
    formats: Sequence[str],
    tool_version: str,
    source_paths: Sequence[str] = (),
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    load_failures: Sequence[Mapping[str, Any]] = (),
    extract_failures: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Assemble the manifest dictionary for one published product."""
    finished = finished_at or datetime.now(timezone.utc)
    started = started_at or finished

    per_source: dict[str, dict[str, Any]] = {}
    for document in documents:
        entry = per_source.setdefault(
            document.source.uri,
            {**document.source.to_dict(), "record_count": 0, "word_count": 0},
        )
        entry["word_count"] = len(document.text.split())

    for record in records:
        entry = per_source.setdefault(
            record.source_uri,
            {
                "uri": record.source_uri,
                "name": record.source_uri.rsplit("/", 1)[-1],
                "media_type": record.source_media_type,
                "sha256": record.source_sha256,
                "size_bytes": None,
                "record_count": 0,
                "word_count": 0,
            },
        )
        entry["record_count"] = int(entry.get("record_count", 0)) + 1

    issues = [i.to_dict() for i in quality.issues]
    truncated_issues = len(issues) > MAX_ISSUES_IN_MANIFEST

    return {
        "manifest_version": MANIFEST_VERSION,
        "product": {
            "name": contract.name,
            "version": contract.version,
            "description": contract.description,
            "schema_hash": contract.schema_hash(),
            "primary_key": list(contract.primary_key),
            "field_count": len(contract.fields),
        },
        "generated_at": finished.isoformat(),
        "run": {
            "started_at": started.isoformat(),
            "duration_seconds": round((finished - started).total_seconds(), 3),
            "tool": "crystallball",
            "tool_version": tool_version,
            "extractors": list(extractors),
            "formats": list(formats),
            "source_paths": list(source_paths),
        },
        "counts": {
            "documents": len(documents),
            "records": len(records),
            "sources": len(per_source),
            "load_failures": len(load_failures),
            "extract_failures": len(extract_failures),
            "errors": quality.error_count,
            "warnings": quality.warning_count,
        },
        "quality": {
            "passed": quality.passed,
            "error_count": quality.error_count,
            "warning_count": quality.warning_count,
            "dropped_fields": quality.dropped_fields,
            "issues": issues[:MAX_ISSUES_IN_MANIFEST],
            "issues_truncated": truncated_issues,
            "fields": [p.to_dict() for p in quality.profiles],
        },
        "contract": contract.to_dict(),
        "files": [file_fingerprint(path) for path in files],
        "sources": sorted(per_source.values(), key=lambda s: str(s.get("uri", ""))),
        "failures": {
            "load": list(load_failures),
            "extract": list(extract_failures),
        },
    }


def write_manifest(manifest: Mapping[str, Any], directory: Path, *, stem: str = "manifest") -> Path:
    """Write ``manifest`` as pretty-printed JSON and return the path."""
    target = directory / f"{stem}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise PublishError(f"could not write {target}: {exc}") from exc
    return target


def read_manifest(path: Path) -> dict[str, Any]:
    """Load a manifest written by :func:`write_manifest`."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PublishError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PublishError(f"manifest {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PublishError(f"manifest {path} is not a JSON object")
    return payload
