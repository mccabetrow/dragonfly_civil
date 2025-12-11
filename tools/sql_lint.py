from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
WATCH_EXTENSIONS: Sequence[str] = (".sql", ".ps1")
PATTERNS: Sequence[str] = (
    "CREATE TABLE",
    "ALTER TABLE",
    "DROP TABLE",
    "INSERT INTO",
    "UPDATE ",
    "DELETE FROM",
)
IGNORED_DIRS: Sequence[Path] = (
    REPO_ROOT / "supabase" / "migrations",
    REPO_ROOT / "supabase" / "db" / "migrations",
    REPO_ROOT / "supabase" / "archive",
    REPO_ROOT / "supabase" / "recovery",
    REPO_ROOT / "tmp",
    REPO_ROOT / "docs",
)
IGNORED_FILES: Sequence[Path] = (REPO_ROOT / "supabase" / "schema.sql",)


def _is_ignored(path: Path) -> bool:
    for ignored in IGNORED_DIRS:
        try:
            if path == ignored or path.is_relative_to(ignored):
                return True
        except ValueError:
            # path and ignored are on different drives
            continue
    return False


def _collect_candidates(root: Path) -> Iterable[Path]:
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        if _is_ignored(current_path):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if not _is_ignored(current_path / d)]
        for name in files:
            candidate = current_path / name
            if candidate in IGNORED_FILES:
                continue
            if candidate.suffix.lower() in WATCH_EXTENSIONS:
                yield candidate


def _scan_file(path: Path) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    upper = text.upper()
    return [pattern for pattern in PATTERNS if pattern in upper]


def run_sql_lint(root: Path) -> List[tuple[Path, List[str]]]:
    violations: List[tuple[Path, List[str]]] = []
    for candidate in _collect_candidates(root):
        matches = _scan_file(candidate)
        if matches:
            violations.append((candidate, matches))
    return violations


def _format_violation(root: Path, path: Path, matches: Sequence[str]) -> str:
    rel = path.relative_to(root)
    return f"- {rel}: found {', '.join(matches)}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail the build if dangerous SQL statements exist outside migrations.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root to scan (defaults to project root)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    violations = run_sql_lint(root)
    if not violations:
        print("[sql_lint] No ad-hoc SQL mutations detected.")
        return 0

    print("[sql_lint] Detected manual SQL outside migrations:")
    for path, matches in violations:
        print(_format_violation(root, path, matches))
    print("[sql_lint] Please move schema/data changes into Supabase migrations.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
