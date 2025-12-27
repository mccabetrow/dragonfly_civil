"""
Dragonfly Audit Logging Test - Gate Integration

Validates the universal ops.audit_log system is properly deployed.

Usage:
    python -m tools.test_audit_logging [--env dev|prod]

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    """Run audit logging validation."""
    parser = argparse.ArgumentParser(description="Validate ops.audit_log deployment")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment (default: from SUPABASE_MODE)",
    )
    args = parser.parse_args()

    # Set environment
    os.environ["SUPABASE_MODE"] = args.env
    print(f"Environment: {args.env.upper()}")

    # Import and run the CLI tests
    from tests.test_audit_logging import run_cli_tests

    return run_cli_tests()


if __name__ == "__main__":
    sys.exit(main())
