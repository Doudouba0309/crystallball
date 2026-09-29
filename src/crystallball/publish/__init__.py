"""Publishing: write records and their manifest as a versioned data product."""

from __future__ import annotations

from .manifest import MANIFEST_VERSION, build_manifest, read_manifest, write_manifest
from .writers import (
    FORMAT_SUFFIX,
    SUPPORTED_FORMATS,
    file_fingerprint,
    write_csv,
    write_jsonl,
    write_parquet,
    write_rows,
)

__all__ = [
    "MANIFEST_VERSION",
    "SUPPORTED_FORMATS",
    "FORMAT_SUFFIX",
    "build_manifest",
    "file_fingerprint",
    "read_manifest",
    "write_csv",
    "write_jsonl",
    "write_manifest",
    "write_parquet",
    "write_rows",
]
