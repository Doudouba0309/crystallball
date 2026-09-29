"""crystallball — turn unstructured content into governed data products.

A four-stage pipeline:

1. **Ingest** — load PDFs, Office files, HTML, text, and images into a uniform
   :class:`~crystallball.models.Document`.
2. **Extract** — derive structured fields with deterministic extractors, a
   pluggable language model, or both.
3. **Validate** — check every record against a :class:`~crystallball.contract.ProductContract`.
4. **Publish** — write versioned artifacts plus a manifest recording lineage,
   quality, and provenance.

Quick start:
    >>> from crystallball import ProductContract, PipelineOptions, run_pipeline
    >>> contract = ProductContract.from_json("examples/products/document_intelligence.json")
    >>> result = run_pipeline(["examples/data"], contract,          # doctest: +SKIP
    ...                       PipelineOptions(out_dir="build_products"))
"""

from __future__ import annotations

# Importing these packages registers the built-in loaders and extractors.
from . import extract, ingest, publish, quality
from .contract import FieldSpec, ProductContract, contract_from_field_names
from .errors import (
    ContractError,
    CrystallballError,
    ExtractError,
    LoadError,
    PublishError,
    UnsupportedMediaType,
)
from .models import (
    ENVELOPE_COLUMNS,
    Document,
    ExtractionResult,
    Record,
    SourceRef,
    TextBlock,
    make_record_id,
)
from .pipeline import (
    PipelineOptions,
    PipelineResult,
    load_and_run,
    records_from_rows,
    rows_from_jsonl,
    run_pipeline,
)
from .version import __version__

__all__ = [
    "__version__",
    # Contracts
    "FieldSpec",
    "ProductContract",
    "contract_from_field_names",
    # Models
    "ENVELOPE_COLUMNS",
    "Document",
    "ExtractionResult",
    "Record",
    "SourceRef",
    "TextBlock",
    "make_record_id",
    # Pipeline
    "PipelineOptions",
    "PipelineResult",
    "run_pipeline",
    "load_and_run",
    "rows_from_jsonl",
    "records_from_rows",
    # Errors
    "CrystallballError",
    "ContractError",
    "ExtractError",
    "LoadError",
    "PublishError",
    "UnsupportedMediaType",
    # Subpackages
    "extract",
    "ingest",
    "publish",
    "quality",
]
