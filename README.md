# crystallball

Turn unstructured content into governed, publishable **data products**.

Point it at a pile of PDFs, Office files, HTML, text, and images. It extracts
structured fields, validates every record against a declared contract, and
publishes versioned artifacts plus a manifest recording lineage, quality, and
provenance.

## Why a contract

Unstructured extraction is easy to do badly and hard to trust. Here, a
`ProductContract` is the gate: an extractor may produce fifty fields, but only
the ones the contract declares are published, and every record is type-checked
before it ships. The contract is also checked *against reality* — a field that
is declared but null in every row is reported, because silently all-null
columns are how data products rot.

## Pipeline

```
SourceRef ──▶ Document ──▶ ExtractionResult ──▶ Record ──▶ data product
  ingest        extract          validate         publish
```

| Stage | Module | Responsibility |
|---|---|---|
| Ingest | `crystallball.ingest` | Load files into a uniform `Document` with located text blocks |
| Extract | `crystallball.extract` | Derive fields: deterministic stats/entities/label-values, or a pluggable LLM |
| Validate | `crystallball.quality` | Contract conformance, key integrity, fill-rate profiling |
| Publish | `crystallball.publish` | JSONL/CSV/Parquet plus `manifest.json`, `contract.json`, `quality.json` |

## Install

The core is dependency-free and runs on a bare interpreter.

```bash
pip install -e .                 # core only
pip install -e '.[all]'          # Office, HTML, image, PDF support
pip install -e '.[dev]'          # adds pytest
```

## Quick start

```bash
crystallball info                              # what is registered
crystallball discover ./data                   # what would be ingested
crystallball extract ./data \
    --contract examples/products/document_intelligence.json \
    --out build_products \
    --format jsonl
crystallball validate build_products/document_intelligence
```

From Python:

```python
from crystallball import PipelineOptions, ProductContract, run_pipeline

contract = ProductContract.from_json("examples/products/document_intelligence.json")
result = run_pipeline(["./data"], contract, PipelineOptions(out_dir="build_products"))

print(result.record_count, result.passed)
```

## What a run produces

```
build_products/document_intelligence/
├── records.jsonl     # one JSON object per document
├── contract.json     # the published interface, with a schema hash
├── quality.json      # issues and per-field fill rates
└── manifest.json     # lineage, provenance, counts, file checksums
```

Every row carries lineage columns — `record_id`, `source_uri`,
`source_sha256`, `source_media_type`, `extractors`, `confidence`,
`extracted_at` — so any value can be traced back to the document it came from.
`record_id` is derived from the content hash, so re-running over unchanged
input is idempotent.

## Adding an extractor

```python
from crystallball.extract import ExtractionResult, register_extractor

class VendorExtractor:
    name = "vendor"

    def extract(self, document):
        if "Vendor:" not in document.text:
            return None                      # abstain; not an error
        return ExtractionResult(
            extractor=self.name,
            fields={"vendor": document.text.split("Vendor:")[1].splitlines()[0].strip()},
            confidence=0.9,
        )

register_extractor(VendorExtractor())
```

Confidence for a record is the **minimum** across contributing extractors: a
record is only as trustworthy as its least reliable field source.

## Using a language model

The library never imports a model provider. Pass a completion callable:

```python
from crystallball.extract import LlmExtractor

extractor = LlmExtractor(
    complete=lambda prompt: my_client.chat(prompt),   # returns JSON text
    fields=["vendor", "total_amount", "due_date"],
    confidence=0.6,
)
```

This keeps credentials and cost control with the caller, and keeps tests offline.

## Status

`0.1.0` — the structure and pipeline are in place and working end to end.
Test coverage and worked examples are the next additions.
