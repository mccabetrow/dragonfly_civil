r"""Simplicity ingest runner.

Runbook — Simplicity → Supabase → Enrichment → Dashboard:
1. Drop the latest Simplicity export in ``data_in\simplicity_export_900.csv`` (or similar).
2. *Dry run preview* (no writes):
    Set-Location C:\Users\mccab\dragonfly_civil
    .\.venv\Scripts\python.exe scripts\sync_simplicity_cases.py --input data_in\simplicity_export_900.csv --dry-run
3. *Real ingest* (writes to Supabase):
    Set-Location C:\Users\mccab\dragonfly_civil
    .\.venv\Scripts\python.exe scripts\sync_simplicity_cases.py --input data_in\simplicity_export_900.csv
    .\.venv\Scripts\python.exe -m tools.doctor
4. Dashboards refresh automatically — /overview for pipeline stats, /collectability for tier filters, /cases for case drawers with enrichment + FOIL history.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from dataclasses import dataclass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.src.simplicity_ingest import (
    DEFAULT_SOURCE,
    _coerce_row,
    ingest_file,
    map_row_to_insert_case_payload,
)


def _default_input() -> Path:
    return Path(__file__).resolve().parents[1] / "data_in" / "simplicity_export.csv"


@dataclass(slots=True)
class PreviewResult:
    processed: int
    ingestable: int
    errors: list[str]
    payload_samples: list[dict[str, object]]


def preview_ingest(
    input_path: Path,
    *,
    source: str = DEFAULT_SOURCE,
    sample_size: int = 3,
) -> PreviewResult:
    if not input_path.exists():
        raise FileNotFoundError(f"CSV file not found: {input_path}")

    processed = 0
    ingestable = 0
    payload_samples: list[dict[str, object]] = []
    errors: list[str] = []

    with input_path.open(mode="r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file is missing a header row")

        for index, raw_row in enumerate(reader, start=1):
            if not raw_row or all((value or "").strip() == "" for value in raw_row.values()):
                continue

            processed += 1
            normalised = _coerce_row(raw_row)
            try:
                payload = map_row_to_insert_case_payload(normalised, source=source)
            except Exception as exc:  # noqa: BLE001 - surfaced to caller
                errors.append(f"row {index}: {exc}")
                continue

            ingestable += 1
            if len(payload_samples) < sample_size:
                payload_samples.append(payload)

    return PreviewResult(
        processed=processed,
        ingestable=ingestable,
        errors=errors,
        payload_samples=payload_samples,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Simplicity case ingest pipeline")
    parser.add_argument(
        "--input",
        dest="input_path",
        default=str(_default_input()),
        help="CSV file to ingest (default: data_in/simplicity_export.csv)",
    )
    parser.add_argument(
        "--source",
        dest="source",
        default=DEFAULT_SOURCE,
        help="Source label recorded on cases (default: simplicity)",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Preview mapping without inserting into Supabase",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input_path)

    if args.dry_run:
        preview = preview_ingest(input_path, source=args.source)

        print(f"[dry-run] Processed: {preview.processed}")
        print(f"[dry-run] Rows ready for insert_case: {preview.ingestable}")
        for idx, payload in enumerate(preview.payload_samples, start=1):
            print(f"[dry-run] Sample payload {idx}:")
            print(json.dumps(payload, indent=2, sort_keys=True))
        if preview.payload_samples and preview.ingestable > len(preview.payload_samples):
            remaining = preview.ingestable - len(preview.payload_samples)
            print(f"[dry-run] …{remaining} more payloads omitted")
        if preview.errors:
            for message in preview.errors:
                print(f"ERROR: {message}", file=sys.stderr)
        return 0 if not preview.errors else 1

    result = ingest_file(input_path, source=args.source)

    print(
        f"Processed {result.processed} rows; inserted {result.inserted}; failed {result.failed}",
        file=sys.stdout,
    )
    if result.errors:
        for message in result.errors:
            print(f"ERROR: {message}", file=sys.stderr)

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
