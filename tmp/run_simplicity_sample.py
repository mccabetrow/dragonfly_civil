from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.simplicity_importer.import_simplicity import import_simplicity_batch


DEFAULT_CSV = PROJECT_ROOT / "tests" / "data" / "simplicity_sample.csv"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Simplicity importer against the default sample file.",
    )
    parser.add_argument(
        "--csv",
        default=str(DEFAULT_CSV),
        help="Path to a Simplicity CSV export (default: tests/data/simplicity_sample.csv)",
    )
    parser.add_argument(
        "--source-system",
        default="simplicity_test_cli",
        help="Source system label to store on imported rows (default: simplicity_test_cli)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"CSV file not found: {csv_path}", file=sys.stderr)
        return 1

    try:
        import_simplicity_batch(str(csv_path), source_system=args.source_system)
    except Exception as exc:  # pragma: no cover - CLI convenience
        print(
            f"Simplicity import FAILED for source_system='{args.source_system}' and file='{csv_path}': {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        f"Simplicity import completed successfully for source_system='{args.source_system}' and file='{csv_path}'",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
