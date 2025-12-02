from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict

from etl.src.importers.jbi_900 import run_jbi_900_import
from etl.src.importers.simplicity_plaintiffs import run_simplicity_import


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Simplicity or JBI importer with consistent options.",
    )
    parser.add_argument(
        "--source",
        choices=["simplicity", "jbi"],
        required=True,
        help="Which importer to run",
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to the vendor CSV file",
    )
    parser.add_argument(
        "--batch-name",
        help="Batch label stored in import_runs (defaults to CSV stem)",
    )
    parser.add_argument(
        "--source-reference",
        help="External reference recorded in import_runs (defaults to batch name)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Apply changes (omit for dry-run)",
    )
    parser.add_argument(
        "--skip-jobs",
        action="store_true",
        help="Skip queue_job RPC calls (useful for local dry-runs)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON response",
    )
    parser.add_argument(
        "--enable-new-pipeline",
        action="store_true",
        help="Also insert into core_judgments to trigger the new enrichment pipeline",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        parser.error(f"CSV file not found: {csv_path}")

    batch_name = args.batch_name or csv_path.stem
    source_reference = args.source_reference or batch_name

    runner: Callable[..., Dict[str, Any]]
    if args.source == "simplicity":
        runner = run_simplicity_import
    else:
        runner = run_jbi_900_import

    result = runner(
        str(csv_path),
        batch_name=batch_name,
        dry_run=not args.commit,
        source_reference=source_reference,
        enqueue_jobs=not args.skip_jobs,
        enable_new_pipeline=args.enable_new_pipeline,
    )

    json.dump(
        result,
        fp=sys.stdout,
        indent=2 if args.pretty else None,
        sort_keys=True,
        default=str,
    )
    print()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
