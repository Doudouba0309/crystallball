"""Writers for published record sets.

Every writer takes the same flat row dicts and returns the number of rows
written, so the pipeline can treat formats interchangeably.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..errors import PublishError

#: Formats the pipeline can emit.
SUPPORTED_FORMATS: tuple[str, ...] = ("jsonl", "csv", "parquet")

#: Extension per format.
FORMAT_SUFFIX: dict[str, str] = {"jsonl": ".jsonl", "csv": ".csv", "parquet": ".parquet"}


def _flatten(value: Any) -> Any:
    """Convert containers to JSON text so flat formats can hold them."""
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def write_jsonl(rows: Sequence[dict[str, Any]], path: Path) -> int:
    """Write newline-delimited JSON, one row per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        raise PublishError(f"could not write {path}: {exc}") from exc
    return len(rows)


def write_csv(rows: Sequence[dict[str, Any]], path: Path, columns: Sequence[str]) -> int:
    """Write CSV with a fixed column order.

    Containers are JSON-encoded so that a list-valued field survives a round
    trip through a flat format.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(columns), extrasaction="ignore"
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _flatten(row.get(key)) for key in columns})
    except OSError as exc:
        raise PublishError(f"could not write {path}: {exc}") from exc
    return len(rows)


def write_parquet(rows: Sequence[dict[str, Any]], path: Path, columns: Sequence[str]) -> int:
    """Write Parquet via pandas and pyarrow.

    Both are optional dependencies, so a clear error is raised when the extra
    is not installed rather than failing deep inside a C extension.
    """
    try:
        import pandas as pd  # noqa: PLC0415 - optional dependency
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise PublishError(
            "parquet output requires pandas; install with: pip install 'crystallball[parquet]'"
        ) from exc

    ordered = [{key: row.get(key) for key in columns} for row in rows]
    frame = pd.DataFrame(ordered, columns=list(columns))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame.to_parquet(path, index=False)
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise PublishError(
            "parquet output requires pyarrow; install with: "
            "pip install 'crystallball[parquet]'"
        ) from exc
    except (OSError, ValueError) as exc:
        raise PublishError(f"could not write {path}: {exc}") from exc
    return len(rows)


def write_rows(
    rows: Sequence[dict[str, Any]],
    directory: Path,
    fmt: str,
    *,
    stem: str = "records",
    columns: Sequence[str] | None = None,
) -> Path:
    """Dispatch to the writer for ``fmt`` and return the written path."""
    if fmt not in SUPPORTED_FORMATS:
        raise PublishError(
            f"unknown format {fmt!r}; supported: {', '.join(SUPPORTED_FORMATS)}"
        )
    target = directory / f"{stem}{FORMAT_SUFFIX[fmt]}"
    if fmt == "jsonl":
        write_jsonl(rows, target)
    elif fmt == "csv":
        write_csv(rows, target, columns or (list(rows[0]) if rows else []))
    else:
        write_parquet(rows, target, columns or (list(rows[0]) if rows else []))
    return target


def file_fingerprint(path: Path) -> dict[str, Any]:
    """Size and SHA-256 of a published file, for downstream verification."""
    data = path.read_bytes()
    return {
        "name": path.name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
