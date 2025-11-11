from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
VERSION_RE = re.compile(r"^(\d{4})_", re.IGNORECASE)


def _next_available(initial_candidate: int, used: set[int]) -> int:
    candidate = max(initial_candidate, 1)
    while candidate in used:
        candidate += 1
    return candidate


def main() -> int:
    if not MIGRATIONS_DIR.exists():
        print(f"Migrations directory not found: {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    files = [path for path in MIGRATIONS_DIR.iterdir() if path.is_file()]
    if not files:
        print("No migration files found.")
        return 0

    grouped: Dict[int, List[Path]] = defaultdict(list)
    unmatched: List[Path] = []

    for path in files:
        match = VERSION_RE.match(path.name)
        if not match:
            unmatched.append(path)
            continue
        version = int(match.group(1))
        grouped[version].append(path)

    if unmatched:
        print("Skipping files without a 4-digit version prefix:")
        for path in sorted(unmatched):
            print(f"  {path.name}")

    version_rows: List[Tuple[str, str]] = []
    duplicate_detected = False

    all_versions = sorted(grouped)
    if not all_versions:
        print("No versioned migration files found.")
        return 0

    # Reserve all existing version numbers so we don't collide with untouched files.
    reserved_versions = {version for version in all_versions}
    next_candidate = max(reserved_versions) + 1 if reserved_versions else 1

    for version in all_versions:
        paths = sorted(grouped[version], key=lambda p: (p.stat().st_mtime, p.name))
        primary = paths[0]
        version_rows.append((primary.name, primary.name))
        if len(paths) > 1:
            duplicate_detected = True
        for duplicate in paths[1:]:
            next_candidate = _next_available(next_candidate, reserved_versions)
            suffix = duplicate.name[5:]
            old_name = duplicate.name
            new_name = f"{next_candidate:04d}_{suffix}"
            new_path = duplicate.with_name(new_name)
            duplicate.rename(new_path)
            version_rows.append((old_name, new_name))
            reserved_versions.add(next_candidate)
            next_candidate += 1

    version_rows.sort(key=lambda row: row[0])

    before_width = max(len("Before"), *(len(row[0]) for row in version_rows))
    after_width = max(len("After"), *(len(row[1]) for row in version_rows))

    print(f"{'Before':{before_width}} | {'After':{after_width}}")
    print(f"{'-' * before_width}-+-{'-' * after_width}")
    for before, after in version_rows:
        print(f"{before:{before_width}} | {after:{after_width}}")

    if not duplicate_detected:
        print("\nNo duplicate migration versions detected; no changes made.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
