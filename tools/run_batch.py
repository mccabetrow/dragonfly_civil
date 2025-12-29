#!/usr/bin/env python3
"""
Dragonfly Civil - Batch Runner CLI
═══════════════════════════════════════════════════════════════════════════════

A CLI tool to manually trigger batch processing for ingested CSV files.

Usage:
    python -m tools.run_batch --batch-id {uuid}
    python -m tools.run_batch --batch-id 12345678-1234-1234-1234-123456789abc

Features:
    - Calls backend's process_batch() directly (no HTTP overhead)
    - Prints a progress bar during processing
    - Prints a final summary table (Total/Ok/Fail)
    - Exits with code 0 on success, 1 on failure

Environment:
    SUPABASE_MODE: dev | prod (determines which Supabase project to use)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.supabase_client import get_supabase_env

# =============================================================================
# CONSTANTS
# =============================================================================

POLL_INTERVAL_SECONDS = 0.5
PROGRESS_BAR_WIDTH = 40


# =============================================================================
# TERMINAL UI HELPERS
# =============================================================================


class TerminalUI:
    """Simple terminal UI for progress and tables."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    DIM = "\033[2m"

    @staticmethod
    def supports_color() -> bool:
        """Check if terminal supports color."""
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    @classmethod
    def c(cls, text: str, color: str) -> str:
        """Colorize text if terminal supports it."""
        if cls.supports_color():
            return f"{color}{text}{cls.RESET}"
        return text

    @classmethod
    def print_header(cls, title: str) -> None:
        """Print a styled header."""
        print()
        print(cls.c("═" * 60, cls.DIM))
        print(cls.c(f"  {title}", cls.BOLD + cls.CYAN))
        print(cls.c("═" * 60, cls.DIM))
        print()

    @classmethod
    def print_progress_bar(
        cls,
        current: int,
        total: int,
        status: str = "Processing",
        bar_width: int = PROGRESS_BAR_WIDTH,
    ) -> None:
        """Print a progress bar that updates in place."""
        if total <= 0:
            percent = 0
            filled = 0
        else:
            percent = min(100, int(100 * current / total))
            filled = int(bar_width * current / total)

        bar = "█" * filled + "░" * (bar_width - filled)

        # Clear line and print progress
        line = f"\r  {status}: [{cls.c(bar, cls.GREEN)}] {percent:3d}% ({current}/{total})"
        sys.stdout.write(line)
        sys.stdout.flush()

    @classmethod
    def print_summary_table(
        cls,
        batch_id: str,
        status: str,
        total: int,
        inserted: int,
        skipped: int,
        failed: int,
        elapsed: float,
    ) -> None:
        """Print a summary table."""
        print()
        print()
        print(cls.c("┌────────────────────────────────────────────┐", cls.DIM))
        print(
            cls.c("│", cls.DIM)
            + cls.c("          BATCH PROCESSING SUMMARY          ", cls.BOLD)
            + cls.c("│", cls.DIM)
        )
        print(cls.c("├────────────────────────────────────────────┤", cls.DIM))

        # Status row with color
        if status == "completed" and failed == 0:
            status_display = cls.c("✓ COMPLETED", cls.GREEN + cls.BOLD)
        elif status == "completed" and failed > 0:
            status_display = cls.c("⚠ PARTIAL", cls.YELLOW + cls.BOLD)
        else:
            status_display = cls.c("✗ FAILED", cls.RED + cls.BOLD)

        print(cls.c("│", cls.DIM) + f"  Status:     {status_display:<33}" + cls.c("│", cls.DIM))
        print(
            cls.c("│", cls.DIM) + f"  Batch ID:   {batch_id[:24]}...       " + cls.c("│", cls.DIM)
        )
        print(
            cls.c("│", cls.DIM)
            + f"  Time:       {elapsed:.2f}s                           "
            + cls.c("│", cls.DIM)
        )

        print(cls.c("├────────────────────────────────────────────┤", cls.DIM))
        print(
            cls.c("│", cls.DIM)
            + "  "
            + cls.c("ROWS", cls.BOLD)
            + "                                       "
            + cls.c("│", cls.DIM)
        )
        print(
            cls.c("│", cls.DIM)
            + f"    Total:    {total:>8}                       "
            + cls.c("│", cls.DIM)
        )
        print(
            cls.c("│", cls.DIM)
            + f"    Inserted: {cls.c(str(inserted).rjust(8), cls.GREEN)}                       "
            + cls.c("│", cls.DIM)
        )
        print(
            cls.c("│", cls.DIM)
            + f"    Skipped:  {skipped:>8}                       "
            + cls.c("│", cls.DIM)
        )

        if failed > 0:
            print(
                cls.c("│", cls.DIM)
                + f"    Failed:   {cls.c(str(failed).rjust(8), cls.RED)}                       "
                + cls.c("│", cls.DIM)
            )
        else:
            print(
                cls.c("│", cls.DIM)
                + f"    Failed:   {failed:>8}                       "
                + cls.c("│", cls.DIM)
            )

        print(cls.c("└────────────────────────────────────────────┘", cls.DIM))
        print()

    @classmethod
    def print_errors(cls, errors: list[dict[str, Any]], max_errors: int = 5) -> None:
        """Print first N errors."""
        if not errors:
            return

        print(cls.c("  First errors:", cls.RED + cls.BOLD))
        for i, err in enumerate(errors[:max_errors]):
            row_idx = err.get("row_index", "?")
            error_msg = err.get("error", "Unknown error")
            # Truncate long error messages
            if len(error_msg) > 50:
                error_msg = error_msg[:47] + "..."
            print(cls.c(f"    Row {row_idx}: ", cls.DIM) + cls.c(error_msg, cls.RED))

        if len(errors) > max_errors:
            print(cls.c(f"    ... and {len(errors) - max_errors} more errors", cls.DIM))
        print()


# =============================================================================
# BATCH PROCESSOR
# =============================================================================


@dataclass
class ProcessingState:
    """Track processing state for progress bar."""

    status: str = "uploaded"
    rows_total: int = 0
    rows_processed: int = 0


async def get_batch_status(batch_id: UUID) -> dict[str, Any] | None:
    """Get current batch status from database."""
    from backend.db import get_connection

    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id,
                status,
                row_count_total,
                row_count_staged,
                row_count_valid,
                row_count_invalid,
                row_count_inserted,
                error_summary
            FROM intake.simplicity_batches
            WHERE id = $1
            """,
            str(batch_id),
        )
        return dict(row) if row else None


async def process_batch_with_progress(batch_id: UUID) -> int:
    """
    Process a batch with progress bar display.

    Returns:
        0 on success, 1 on failure
    """
    from backend.services.ingestion_service import BatchProcessResult, process_batch

    ui = TerminalUI

    # Print header
    ui.print_header(f"Processing Batch: {batch_id}")
    print(f"  Environment: {get_supabase_env()}")
    print()

    # Get initial batch info
    batch_info = await get_batch_status(batch_id)
    if not batch_info:
        print(ui.c(f"  ✗ Batch not found: {batch_id}", ui.RED))
        return 1

    total_rows = batch_info.get("row_count_total") or 0
    current_status = batch_info.get("status", "unknown")

    print(f"  Current status: {current_status}")
    print(f"  Total rows: {total_rows}")
    print()

    if current_status in ("completed", "failed"):
        print(ui.c(f"  ⚠ Batch already processed: {current_status}", ui.YELLOW))
        return 0 if current_status == "completed" else 1

    # Start processing
    start_time = time.time()

    # Start the actual processing in background
    process_task = asyncio.create_task(process_batch(batch_id))

    # Poll for progress updates while processing
    last_status = current_status
    while not process_task.done():
        # Check current status
        batch_info = await get_batch_status(batch_id)
        if batch_info:
            current_status = batch_info.get("status", "unknown")
            processed = batch_info.get("row_count_staged") or 0

            # Map status to progress
            status_progress = {
                "uploaded": ("Uploading...", 0),
                "staging": ("Staging rows...", 20),
                "transforming": ("Transforming...", 50),
                "upserting": ("Inserting...", 80),
                "completed": ("Complete", 100),
                "failed": ("Failed", 100),
            }

            status_text, base_progress = status_progress.get(current_status, (current_status, 0))

            # Show progress bar
            if total_rows > 0:
                ui.print_progress_bar(
                    max(processed, base_progress),
                    max(total_rows, 100),
                    status_text,
                )

            if current_status != last_status:
                last_status = current_status

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    # Get the result
    try:
        result: BatchProcessResult = await process_task
    except Exception as e:
        elapsed = time.time() - start_time
        print()
        print()
        print(ui.c(f"  ✗ Processing failed: {e}", ui.RED))
        return 1

    elapsed = time.time() - start_time

    # Clear progress bar line
    print("\r" + " " * 80 + "\r", end="")

    # Print summary
    ui.print_summary_table(
        batch_id=str(result.batch_id),
        status=result.status,
        total=result.rows_processed,
        inserted=result.rows_inserted,
        skipped=result.rows_skipped,
        failed=result.rows_failed,
        elapsed=elapsed,
    )

    # Print errors if any
    if result.errors:
        ui.print_errors(result.errors)

    return 0 if result.status == "completed" else 1


# =============================================================================
# MAIN
# =============================================================================


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Dragonfly Batch Runner - Process uploaded CSV batches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.run_batch --batch-id 12345678-1234-1234-1234-123456789abc
    python -m tools.run_batch -b 12345678-1234-1234-1234-123456789abc
        """,
    )
    parser.add_argument(
        "--batch-id",
        "-b",
        type=str,
        required=True,
        help="UUID of the batch to process",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output (just print summary)",
    )

    args = parser.parse_args()

    # Validate UUID
    try:
        batch_id = UUID(args.batch_id)
    except ValueError:
        print(f"Error: Invalid UUID format: {args.batch_id}", file=sys.stderr)
        return 1

    # Configure logging
    log_level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Run the batch processor
    try:
        return asyncio.run(process_batch_with_progress(batch_id))
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
