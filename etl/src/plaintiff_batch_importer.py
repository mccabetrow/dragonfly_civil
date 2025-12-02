"""Batch plaintiff import helper for running the single-file importer over many CSVs.

This CLI expands a glob pattern, reuses a single database connection, and
aggregates statistics so operators can validate large plaintiff loads in one
pass. It defaults to dry-run mode; add ``--commit`` once the plan looks safe.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import logging
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import psycopg

from .foil_utils import _resolve_db_url
from .plaintiff_importer import (
    ImportStats,
    _configure_logging,
    _log_summary,
    _process_candidates,
    _read_csv,
)

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch import plaintiffs from multiple CSV files"
    )
    parser.add_argument(
        "--glob",
        dest="glob_pattern",
        required=True,
        help="Glob pattern for plaintiff CSV files",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing to the database (default)",
    )
    mode_group.add_argument(
        "--commit",
        action="store_true",
        help="Apply the updates to the database",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def _expand_glob(pattern: str) -> List[Path]:
    recursive = "**" in pattern
    paths = [Path(candidate) for candidate in glob.glob(pattern, recursive=recursive)]
    return sorted(path for path in paths if path.is_file())


def _merge_stats(target: ImportStats, source: ImportStats) -> None:
    target.total_rows += source.total_rows
    target.rows_skipped += source.rows_skipped
    target.created_plaintiffs += source.created_plaintiffs
    target.updated_plaintiffs += source.updated_plaintiffs
    target.created_contacts += source.created_contacts
    target.duplicate_contacts += source.duplicate_contacts
    target.status_entries += source.status_entries
    for example in source.examples:
        if len(target.examples) >= 3:
            break
        target.examples.append(example)


def _summarize_per_file(results: List[Tuple[Path, ImportStats]]) -> None:
    if not results:
        return
    logger.info("Per-file summary:")
    for path, stats in results:
        logger.info(
            " • %s -> rows=%d skipped=%d created=%d updated=%d contacts=%d dupes=%d",
            path,
            stats.total_rows,
            stats.rows_skipped,
            stats.created_plaintiffs,
            stats.updated_plaintiffs,
            stats.created_contacts,
            stats.duplicate_contacts,
        )


def _run_cli(argv: Optional[Sequence[str]]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    csv_paths = _expand_glob(args.glob_pattern)
    if not csv_paths:
        logger.warning("No CSV files matched pattern: %s", args.glob_pattern)
        return 0

    dry_run = True
    if args.commit:
        dry_run = False
    elif args.dry_run:
        dry_run = True
    else:
        logger.warning(
            "No mode flag supplied; defaulting to dry-run. Pass --commit to persist changes."
        )
    commit_changes = not dry_run

    try:
        db_url = _resolve_db_url()
    except Exception as exc:  # pragma: no cover - configuration guard
        logger.error("Unable to resolve Supabase database URL: %s", exc)
        return 1

    overall_stats = ImportStats()
    per_file_results: List[Tuple[Path, ImportStats]] = []
    failures: List[Tuple[Path, Exception]] = []

    try:
        with psycopg.connect(db_url, autocommit=dry_run) as conn:
            for path in csv_paths:
                logger.info("Processing %s", path)
                try:
                    parse_result = _read_csv(path)
                except ValueError as exc:
                    logger.error("CSV validation failed for %s: %s", path, exc)
                    failures.append((path, exc))
                    continue

                file_stats = ImportStats(
                    total_rows=parse_result.total_rows,
                    rows_skipped=parse_result.rows_skipped,
                )

                if parse_result.candidates:
                    try:
                        file_stats = _process_candidates(
                            conn,
                            parse_result.candidates,
                            commit=commit_changes,
                            stats=file_stats,
                        )
                        if commit_changes:
                            conn.commit()
                    except Exception as exc:  # noqa: BLE001 - capture per-file errors
                        failures.append((path, exc))
                        logger.error("Import failed for %s: %s", path, exc)
                        if commit_changes:
                            try:
                                conn.rollback()
                            except (
                                Exception
                            ) as rollback_exc:  # pragma: no cover - defensive rollback
                                logger.error(
                                    "Rollback failed after %s: %s", path, rollback_exc
                                )
                                return 1
                        continue
                else:
                    logger.info("No valid plaintiff rows in %s", path)

                per_file_results.append((path, file_stats))
                decorated_examples = [
                    f"{path.name}: {example}" for example in file_stats.examples
                ]
                file_stats.examples = decorated_examples[:3]
                _merge_stats(overall_stats, file_stats)
    except Exception as exc:  # pragma: no cover - connection guard
        logger.error("Batch importer failed: %s", exc)
        return 1

    _summarize_per_file(per_file_results)
    _log_summary(overall_stats, commit=commit_changes)

    if failures:
        logger.error("Encountered %d file error(s):", len(failures))
        for path, err in failures:
            logger.error(" • %s — %s", path, err)

    return 1 if failures else 0


async def main(argv: Optional[Sequence[str]] = None) -> int:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run_cli, argv)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(asyncio.run(main()))
