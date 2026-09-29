"""Command line interface.

Exit codes:
    0  success
    1  the run failed, or validation found errors
    2  usage error (raised by argparse)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence, TextIO

from .contract import ProductContract
from .errors import CrystallballError
from .extract.base import available_extractors
from .ingest.base import detect_media_type, discover_sources, supported_media_types
from .pipeline import (
    PipelineOptions,
    PipelineResult,
    records_from_rows,
    rows_from_jsonl,
    run_pipeline,
)
from .publish.writers import SUPPORTED_FORMATS
from .quality.checks import QualityReport, validate_records
from .version import __version__

PROGRAM = "crystallball"


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Turn unstructured content into governed, publishable data products."
        ),
    )
    parser.add_argument("--version", action="version", version=f"{PROGRAM} {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- info ------------------------------------------------------------
    subparsers.add_parser(
        "info", help="show registered loaders, extractors, and media types"
    )

    # -- discover --------------------------------------------------------
    discover = subparsers.add_parser(
        "discover", help="list the files a run would ingest, without reading them"
    )
    discover.add_argument("paths", nargs="+", help="files or directories to scan")
    discover.add_argument(
        "--no-recursive", action="store_true", help="do not descend into directories"
    )
    discover.add_argument("--json", action="store_true", help="emit JSON")

    # -- extract ---------------------------------------------------------
    extract = subparsers.add_parser(
        "extract", help="run extraction and publish a data product"
    )
    extract.add_argument("paths", nargs="+", help="files or directories to ingest")
    extract.add_argument(
        "-c", "--contract", required=True, help="path to a product contract JSON file"
    )
    extract.add_argument(
        "-o", "--out", required=True, help="directory to write the product into"
    )
    extract.add_argument(
        "-f",
        "--format",
        action="append",
        choices=list(SUPPORTED_FORMATS),
        dest="formats",
        help=f"output format, repeatable (default: jsonl). choices: {', '.join(SUPPORTED_FORMATS)}",
    )
    extract.add_argument(
        "-e",
        "--extractor",
        action="append",
        dest="extractors",
        help="extractor to run, repeatable (default: all registered)",
    )
    extract.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if validation finds errors, after writing artifacts",
    )
    extract.add_argument(
        "--no-recursive", action="store_true", help="do not descend into directories"
    )
    extract.add_argument(
        "--no-envelope",
        action="store_true",
        help="omit lineage columns (record_id, source_uri, confidence, ...)",
    )
    extract.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        help="flag records below this confidence (default: 0.5)",
    )
    extract.add_argument("--json", action="store_true", help="emit a JSON summary")
    extract.add_argument("--quiet", action="store_true", help="suppress the summary")

    # -- validate --------------------------------------------------------
    validate = subparsers.add_parser(
        "validate", help="re-validate a published product against its contract"
    )
    validate.add_argument("product_dir", help="a directory written by 'extract'")
    validate.add_argument("--json", action="store_true", help="emit JSON")

    return parser


# -- output helpers ------------------------------------------------------
def _print_quality(report: QualityReport, stream: TextIO, *, limit: int = 10) -> None:
    """Print a human-readable quality summary."""
    status = "PASS" if report.passed else "FAIL"
    print(
        f"quality: {status}  "
        f"({report.error_count} error(s), {report.warning_count} warning(s), "
        f"{report.record_count} record(s))",
        file=stream,
    )
    for issue in report.issues[:limit]:
        marker = {"error": "x", "warning": "!", "info": "-"}.get(issue.severity, "?")
        location = f" [{issue.record_id}]" if issue.record_id else ""
        print(f"  {marker} {issue.code}{location}: {issue.message}", file=stream)
    remaining = len(report.issues) - limit
    if remaining > 0:
        print(f"  ... and {remaining} more issue(s)", file=stream)


def _print_result(result: PipelineResult, stream: TextIO) -> None:
    print(
        f"product: {result.product_name}\n"
        f"  sources considered: {result.sources_considered}\n"
        f"  documents loaded:   {result.document_count}\n"
        f"  records published:  {result.record_count}\n"
        f"  load failures:      {len(result.load_failures)}\n"
        f"  extract failures:   {len(result.extract_failures)}\n"
        f"  output:             {result.product_dir}",
        file=stream,
    )
    for path in result.files:
        print(f"    - {path.name}", file=stream)
    if result.quality is not None:
        _print_quality(result.quality, stream)
    for failure in result.load_failures[:5]:
        print(f"  ! load failed: {failure['path']}: {failure['error']}", file=stream)


# -- commands ------------------------------------------------------------
def _cmd_info(args: argparse.Namespace) -> int:
    print(f"{PROGRAM} {__version__}")
    print(f"\nloaders ({len(supported_media_types())} media types):")
    for media_type in supported_media_types():
        print(f"  - {media_type}")
    print("\nwildcard loaders:")
    print("  - image/*")
    print(f"\nextractors: {', '.join(available_extractors())}")
    print(f"output formats: {', '.join(SUPPORTED_FORMATS)}")
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    files = discover_sources(args.paths, recursive=not args.no_recursive)
    entries = [
        {
            "path": str(path),
            "media_type": detect_media_type(path),
            "size_bytes": path.stat().st_size,
        }
        for path in files
    ]
    if args.json:
        print(json.dumps({"count": len(entries), "files": entries}, indent=2))
        return 0

    counts = Counter(entry["media_type"] for entry in entries)
    for entry in entries:
        print(f"{entry['media_type']:<75} {entry['size_bytes']:>10}  {entry['path']}")
    print(f"\n{len(entries)} file(s)")
    for media_type, count in sorted(counts.items()):
        print(f"  {count:>5}  {media_type}")
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    contract = ProductContract.from_json(args.contract)
    options = PipelineOptions(
        out_dir=Path(args.out),
        formats=tuple(args.formats) if args.formats else ("jsonl",),
        extractor_names=tuple(args.extractors) if args.extractors else None,
        recursive=not args.no_recursive,
        strict=args.strict,
        include_envelope=not args.no_envelope,
        low_confidence_threshold=args.min_confidence,
    )
    result = run_pipeline(args.paths, contract, options)

    if args.json:
        print(json.dumps(result.summary(), indent=2, default=str))
    elif not args.quiet:
        _print_result(result, sys.stdout)

    if args.strict and not result.passed:
        return 1
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    product_dir = Path(args.product_dir)
    if not product_dir.is_dir():
        print(f"error: not a directory: {product_dir}", file=sys.stderr)
        return 1

    contract_path = product_dir / "contract.json"
    if not contract_path.is_file():
        print(
            f"error: {contract_path} not found; expected a product directory "
            f"written by '{PROGRAM} extract'",
            file=sys.stderr,
        )
        return 1
    contract = ProductContract.from_json(contract_path)

    records_path = product_dir / "records.jsonl"
    if not records_path.is_file():
        print(
            f"error: {records_path} not found; 'validate' currently reads JSONL only. "
            f"Re-run extract with --format jsonl to enable re-validation.",
            file=sys.stderr,
        )
        return 1

    rows = rows_from_jsonl(records_path)
    records = records_from_rows(rows, contract)
    report = validate_records(records, contract)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        _print_quality(report, sys.stdout)
        if report.profiles:
            print("\nfields:")
            for profile in report.profiles:
                print(
                    f"  {profile.name:<28} fill={profile.fill_rate:>6.3f} "
                    f"distinct={profile.distinct:<6} non_null={profile.non_null}"
                )
    return 0 if report.passed else 1


_COMMANDS = {
    "info": _cmd_info,
    "discover": _cmd_discover,
    "extract": _cmd_extract,
    "validate": _cmd_validate,
}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS[args.command]
    try:
        return handler(args)
    except CrystallballError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
