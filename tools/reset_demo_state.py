#!/usr/bin/env python3
"""
Dragonfly Civil - Demo State Reset Tool
═══════════════════════════════════════════════════════════════════════════════

Safely resets the intake schema for demo purposes by truncating intake tables.

Usage:
    python -m tools.reset_demo_state          # Interactive confirmation
    python -m tools.reset_demo_state --force  # Skip confirmation (for automation)

Safety:
    - Requires VITE_DEMO_MODE=true OR explicit --force flag
    - Interactive confirmation prompt unless --force is used
    - Only affects intake schema (batches, raw_rows, failed_rows)

Environment:
    SUPABASE_MODE: dev | prod (determines which Supabase project to use)
    VITE_DEMO_MODE: true (optional - enables automatic mode)
"""

from __future__ import annotations

import argparse
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.supabase_client import get_supabase_env

# =============================================================================
# TERMINAL UI
# =============================================================================


class TerminalUI:
    """Simple terminal UI helpers."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    DIM = "\033[2m"

    @staticmethod
    def supports_color() -> bool:
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    @classmethod
    def c(cls, text: str, color: str) -> str:
        if cls.supports_color():
            return f"{color}{text}{cls.RESET}"
        return text

    @classmethod
    def print_warning(cls, msg: str) -> None:
        print(cls.c(f"⚠️  {msg}", cls.YELLOW))

    @classmethod
    def print_success(cls, msg: str) -> None:
        print(cls.c(f"✅ {msg}", cls.GREEN))

    @classmethod
    def print_error(cls, msg: str) -> None:
        print(cls.c(f"❌ {msg}", cls.RED))

    @classmethod
    def print_info(cls, msg: str) -> None:
        print(cls.c(f"ℹ️  {msg}", cls.CYAN))


# =============================================================================
# RESET LOGIC
# =============================================================================


def reset_intake_tables(force: bool = False) -> bool:
    """
    Truncate all intake tables for demo reset.

    Args:
        force: Skip confirmation prompt

    Returns:
        True if reset was successful, False otherwise
    """
    from backend.utils.db import get_db_connection

    ui = TerminalUI

    env = get_supabase_env()
    demo_mode = os.environ.get("VITE_DEMO_MODE", "").lower() == "true"

    print()
    ui.print_warning("DEMO STATE RESET")
    print(f"   Environment: {env}")
    print(f"   Demo Mode:   {demo_mode}")
    print()

    # Safety check: require demo mode OR force flag
    if not demo_mode and not force:
        ui.print_error("Safety check failed!")
        print("   Either set VITE_DEMO_MODE=true or use --force flag")
        print()
        return False

    # Interactive confirmation unless forced
    if not force:
        print(ui.c("This will TRUNCATE the following tables:", ui.BOLD))
        print("   • intake.simplicity_batches")
        print("   • intake.simplicity_raw_rows")
        print("   • intake.simplicity_failed_rows")
        print()

        try:
            response = input("Are you sure? (y/n): ").strip().lower()
            if response not in ("y", "yes"):
                ui.print_info("Reset cancelled by user")
                return False
        except (KeyboardInterrupt, EOFError):
            print()
            ui.print_info("Reset cancelled")
            return False

    print()
    ui.print_info("Connecting to database...")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Truncate intake tables with CASCADE
                cur.execute(
                    """
                    TRUNCATE TABLE
                        intake.simplicity_batches,
                        intake.simplicity_raw_rows,
                        intake.simplicity_failed_rows
                    CASCADE;
                    """
                )
                conn.commit()

        print()
        ui.print_success("Database Intake Cleared")
        print("   Tables truncated:")
        print("   • intake.simplicity_batches")
        print("   • intake.simplicity_raw_rows")
        print("   • intake.simplicity_failed_rows")
        print()

        return True

    except Exception as e:
        ui.print_error(f"Reset failed: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Reset demo state by truncating intake tables",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Safety:
    This tool requires VITE_DEMO_MODE=true OR --force flag to run.
    Without --force, you will be prompted for confirmation.

Examples:
    python -m tools.reset_demo_state          # Interactive mode
    python -m tools.reset_demo_state --force  # Automation mode
        """,
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Skip confirmation prompt (for automation)",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Supabase environment (defaults to SUPABASE_MODE)",
    )

    args = parser.parse_args()

    # Set environment if specified
    if args.env:
        os.environ["SUPABASE_MODE"] = args.env

    success = reset_intake_tables(force=args.force)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
