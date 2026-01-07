#!/usr/bin/env python3
"""
Dragonfly Civil - Backend Structure Refactoring Script

Migrates from a flat backend/ structure to a domain-driven "North Star" layout:

    backend/
    ├── api/           # FastAPI routers and request handling
    │   ├── main.py    # Application entry point
    │   └── routers/   # All router modules
    ├── core/          # Config, bootstrap, security (already exists)
    ├── services/      # Business logic (already exists)
    ├── workers/       # Background jobs (already exists)
    └── utils/         # Helper utilities (already exists)

This script:
1. Moves files to new locations
2. Updates all imports across the codebase
3. Creates __init__.py files where needed
4. Provides dry-run mode for safety

Usage:
    python -m tools.refactor_structure --dry-run    # Preview changes
    python -m tools.refactor_structure --apply      # Execute refactor
    python -m tools.refactor_structure --validate   # Check import consistency

Author: Dragonfly DevOps
Date: 2026-01-05
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# =============================================================================
# Configuration
# =============================================================================

# Project root (relative to this script)
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
BACKEND_ROOT = PROJECT_ROOT / "backend"

# Files/directories to ignore
IGNORE_PATTERNS = {
    "__pycache__",
    ".git",
    ".venv",
    "node_modules",
    ".pytest_cache",
    "*.pyc",
    "*.pyo",
}

# Move operations: (source, destination)
# Paths are relative to BACKEND_ROOT
MOVE_OPERATIONS: list[tuple[str, str]] = [
    # Routers move to api/routers/
    ("routers", "api/routers"),
]

# Import replacement patterns: (old_pattern, new_pattern)
# These are regex patterns applied to all .py files
IMPORT_REPLACEMENTS: list[tuple[str, str]] = [
    # Routers import path changes
    (r"from backend\.routers\.", r"from backend.api.routers."),
    (r"from \.routers\.", r"from .api.routers."),
    (r"import backend\.routers\.", r"import backend.api.routers."),
    # Handle relative imports in main.py after move
    (r"from \.\.routers\.", r"from .api.routers."),
]

# Additional replacements when main.py moves to api/
MAIN_PY_IMPORT_REPLACEMENTS: list[tuple[str, str]] = [
    # Adjust relative imports for new location
    (r"from \.routers\.", r"from .api.routers."),
    (r"from \.config", r"from ..config"),
    (r"from \.core\.", r"from ..core."),
    (r"from \.db", r"from ..db"),
    (r"from \.scheduler", r"from ..scheduler"),
    (r"from \.asyncio_compat", r"from ..asyncio_compat"),
    (r"from \. import", r"from .. import"),
]


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class FileMove:
    """Represents a file move operation."""

    source: Path
    destination: Path
    executed: bool = False
    error: Optional[str] = None


@dataclass
class ImportUpdate:
    """Represents an import update in a file."""

    file_path: Path
    line_number: int
    old_line: str
    new_line: str
    executed: bool = False


@dataclass
class RefactorPlan:
    """Complete refactoring plan."""

    moves: list[FileMove] = field(default_factory=list)
    import_updates: list[ImportUpdate] = field(default_factory=list)
    init_files_to_create: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# =============================================================================
# Refactoring Engine
# =============================================================================


class RefactorEngine:
    """Engine for planning and executing the refactor."""

    def __init__(self, project_root: Path, dry_run: bool = True, verbose: bool = False):
        self.project_root = project_root
        self.backend_root = project_root / "backend"
        self.dry_run = dry_run
        self.verbose = verbose
        self.plan = RefactorPlan()

    def log(self, message: str, level: str = "INFO") -> None:
        """Log with formatting."""
        icons = {
            "INFO": "ℹ️",
            "MOVE": "📦",
            "UPDATE": "✏️",
            "CREATE": "📝",
            "SKIP": "⏭️",
            "ERROR": "❌",
            "WARN": "⚠️",
            "OK": "✅",
        }
        icon = icons.get(level, "")
        print(f"{icon} [{level}] {message}")

    def log_verbose(self, message: str) -> None:
        """Log only in verbose mode."""
        if self.verbose:
            self.log(message, "INFO")

    def _should_ignore(self, path: Path) -> bool:
        """Check if path should be ignored."""
        for pattern in IGNORE_PATTERNS:
            if pattern.startswith("*"):
                if path.name.endswith(pattern[1:]):
                    return True
            elif pattern in path.parts:
                return True
        return False

    def _find_python_files(self, root: Optional[Path] = None) -> list[Path]:
        """Find all Python files in the project."""
        root = root or self.project_root
        python_files = []

        for path in root.rglob("*.py"):
            if not self._should_ignore(path):
                python_files.append(path)

        return sorted(python_files)

    def _plan_directory_move(self, source_rel: str, dest_rel: str) -> None:
        """Plan moving a directory and its contents."""
        source = self.backend_root / source_rel
        dest = self.backend_root / dest_rel

        if not source.exists():
            self.log(f"Source does not exist: {source_rel}", "SKIP")
            return

        if dest.exists() and source_rel != dest_rel:
            # Destination exists - need to merge
            self.log(f"Destination exists, will merge: {dest_rel}", "WARN")

        if source.is_dir():
            for item in source.rglob("*"):
                if item.is_file() and not self._should_ignore(item):
                    rel_path = item.relative_to(source)
                    dest_path = dest / rel_path
                    self.plan.moves.append(FileMove(source=item, destination=dest_path))
        else:
            self.plan.moves.append(FileMove(source=source, destination=dest))

    def _plan_import_updates(self) -> None:
        """Scan all Python files and plan import updates."""
        python_files = self._find_python_files()

        for file_path in python_files:
            try:
                content = file_path.read_text(encoding="utf-8")
                lines = content.split("\n")

                for line_num, line in enumerate(lines, 1):
                    for old_pattern, new_pattern in IMPORT_REPLACEMENTS:
                        if re.search(old_pattern, line):
                            new_line = re.sub(old_pattern, new_pattern, line)
                            if new_line != line:
                                self.plan.import_updates.append(
                                    ImportUpdate(
                                        file_path=file_path,
                                        line_number=line_num,
                                        old_line=line,
                                        new_line=new_line,
                                    )
                                )
            except Exception as e:
                self.plan.errors.append(f"Error reading {file_path}: {e}")

    def _plan_init_files(self) -> None:
        """Plan __init__.py creation in new directories."""
        # Check all destination directories
        dest_dirs = set()
        for move in self.plan.moves:
            dest_dirs.add(move.destination.parent)

        # Also check the api/routers target
        api_routers = self.backend_root / "api" / "routers"
        dest_dirs.add(api_routers)
        dest_dirs.add(api_routers.parent)

        for dir_path in dest_dirs:
            init_file = dir_path / "__init__.py"
            if not init_file.exists():
                self.plan.init_files_to_create.append(init_file)

    def plan_refactor(self) -> RefactorPlan:
        """Create the complete refactoring plan."""
        self.log("Planning refactor operations...")

        # Plan moves
        for source, dest in MOVE_OPERATIONS:
            self._plan_directory_move(source, dest)

        # Plan import updates
        self._plan_import_updates()

        # Plan __init__.py files
        self._plan_init_files()

        return self.plan

    def execute_moves(self) -> int:
        """Execute file move operations."""
        success_count = 0

        for move in self.plan.moves:
            try:
                if self.dry_run:
                    rel_src = move.source.relative_to(self.project_root)
                    rel_dst = move.destination.relative_to(self.project_root)
                    self.log(f"Would move: {rel_src} -> {rel_dst}", "MOVE")
                    success_count += 1
                else:
                    # Create destination directory
                    move.destination.parent.mkdir(parents=True, exist_ok=True)

                    # Move file
                    if move.destination.exists():
                        self.log(f"Destination exists, backing up: {move.destination}", "WARN")
                        backup = move.destination.with_suffix(".bak")
                        shutil.move(str(move.destination), str(backup))

                    shutil.move(str(move.source), str(move.destination))
                    move.executed = True
                    success_count += 1

                    rel_src = move.source.relative_to(self.project_root)
                    rel_dst = move.destination.relative_to(self.project_root)
                    self.log(f"Moved: {rel_src} -> {rel_dst}", "MOVE")

            except Exception as e:
                move.error = str(e)
                self.log(f"Failed to move {move.source}: {e}", "ERROR")

        return success_count

    def execute_import_updates(self) -> int:
        """Execute import replacements in files."""
        # Group updates by file
        updates_by_file: dict[Path, list[ImportUpdate]] = {}
        for update in self.plan.import_updates:
            if update.file_path not in updates_by_file:
                updates_by_file[update.file_path] = []
            updates_by_file[update.file_path].append(update)

        success_count = 0

        for file_path, updates in updates_by_file.items():
            try:
                if self.dry_run:
                    rel_path = file_path.relative_to(self.project_root)
                    self.log(f"Would update {len(updates)} import(s) in: {rel_path}", "UPDATE")
                    if self.verbose:
                        for u in updates:
                            print(f"      L{u.line_number}: {u.old_line.strip()}")
                            print(f"            -> {u.new_line.strip()}")
                    success_count += len(updates)
                else:
                    content = file_path.read_text(encoding="utf-8")

                    # Apply all replacements
                    for old_pattern, new_pattern in IMPORT_REPLACEMENTS:
                        content = re.sub(old_pattern, new_pattern, content)

                    file_path.write_text(content, encoding="utf-8")

                    for update in updates:
                        update.executed = True

                    success_count += len(updates)
                    rel_path = file_path.relative_to(self.project_root)
                    self.log(f"Updated {len(updates)} import(s) in: {rel_path}", "UPDATE")

            except Exception as e:
                self.log(f"Failed to update {file_path}: {e}", "ERROR")

        return success_count

    def execute_init_files(self) -> int:
        """Create __init__.py files."""
        success_count = 0

        for init_path in self.plan.init_files_to_create:
            try:
                if self.dry_run:
                    rel_path = init_path.relative_to(self.project_root)
                    self.log(f"Would create: {rel_path}", "CREATE")
                    success_count += 1
                else:
                    init_path.parent.mkdir(parents=True, exist_ok=True)
                    init_path.write_text(
                        '"""Auto-generated __init__.py for package structure."""\n',
                        encoding="utf-8",
                    )
                    success_count += 1
                    rel_path = init_path.relative_to(self.project_root)
                    self.log(f"Created: {rel_path}", "CREATE")

            except Exception as e:
                self.log(f"Failed to create {init_path}: {e}", "ERROR")

        return success_count

    def cleanup_empty_dirs(self) -> int:
        """Remove empty directories after moves."""
        removed = 0

        # Check directories that should now be empty
        for move in self.plan.moves:
            parent = move.source.parent
            if parent.exists() and parent.is_dir():
                # Check if empty (only __pycache__ or nothing)
                contents = list(parent.iterdir())
                if not contents or all(c.name == "__pycache__" for c in contents):
                    if self.dry_run:
                        rel_path = parent.relative_to(self.project_root)
                        self.log(f"Would remove empty dir: {rel_path}", "INFO")
                        removed += 1
                    else:
                        try:
                            shutil.rmtree(str(parent))
                            removed += 1
                            rel_path = parent.relative_to(self.project_root)
                            self.log(f"Removed empty dir: {rel_path}", "INFO")
                        except Exception as e:
                            self.log(f"Failed to remove {parent}: {e}", "WARN")

        return removed

    def execute(self) -> bool:
        """Execute the full refactoring plan."""
        print("\n" + "=" * 70)
        print("  DRAGONFLY CIVIL - BACKEND STRUCTURE REFACTOR")
        print("  Mode:", "DRY RUN (preview only)" if self.dry_run else "APPLY (making changes)")
        print("=" * 70 + "\n")

        # Create plan
        self.plan_refactor()

        # Summary
        print("-" * 70)
        print("  Planned Operations:")
        print(f"    - File moves:      {len(self.plan.moves)}")
        print(f"    - Import updates:  {len(self.plan.import_updates)}")
        print(f"    - Init files:      {len(self.plan.init_files_to_create)}")
        print("-" * 70 + "\n")

        if not self.plan.moves and not self.plan.import_updates:
            self.log("Nothing to refactor - structure already matches North Star!", "OK")
            return True

        # Execute
        moved = self.execute_moves()
        updated = self.execute_import_updates()
        created = self.execute_init_files()
        cleaned = self.cleanup_empty_dirs()

        # Summary
        print("\n" + "=" * 70)
        print("  SUMMARY:")
        print(f"    - Files moved:        {moved}")
        print(f"    - Imports updated:    {updated}")
        print(f"    - Init files created: {created}")
        print(f"    - Empty dirs removed: {cleaned}")

        if self.plan.errors:
            print(f"\n  ERRORS ({len(self.plan.errors)}):")
            for error in self.plan.errors:
                print(f"    - {error}")

        print("=" * 70 + "\n")

        if self.dry_run:
            self.log("DRY RUN complete. Run with --apply to execute.", "INFO")
        else:
            self.log("Refactor complete!", "OK")

        return len(self.plan.errors) == 0


class ImportValidator:
    """Validates import consistency after refactor."""

    def __init__(self, project_root: Path, verbose: bool = False):
        self.project_root = project_root
        self.verbose = verbose

    def validate(self) -> bool:
        """Check for broken imports and inconsistencies."""
        print("\n" + "=" * 70)
        print("  IMPORT VALIDATION")
        print("=" * 70 + "\n")

        issues = []

        # Check for old import patterns that should have been replaced
        old_patterns = [
            (r"from backend\.routers\.", "backend.routers should be backend.api.routers"),
            (r"from \.routers\.", ".routers should be .api.routers (in most cases)"),
        ]

        backend_root = self.project_root / "backend"

        for py_file in backend_root.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                rel_path = py_file.relative_to(self.project_root)

                for pattern, message in old_patterns:
                    matches = re.findall(pattern, content)
                    if matches:
                        issues.append(f"{rel_path}: {message}")

            except Exception as e:
                issues.append(f"Error reading {py_file}: {e}")

        # Check that expected directories exist
        expected_dirs = [
            "backend/api",
            "backend/api/routers",
            "backend/core",
            "backend/services",
            "backend/utils",
            "backend/workers",
        ]

        for dir_rel in expected_dirs:
            dir_path = self.project_root / dir_rel
            if not dir_path.exists():
                issues.append(f"Expected directory missing: {dir_rel}")
            elif not (dir_path / "__init__.py").exists():
                issues.append(f"Missing __init__.py in: {dir_rel}")

        # Report
        if issues:
            print("❌ VALIDATION FAILED - Issues found:\n")
            for issue in issues:
                print(f"   • {issue}")
            print()
            return False
        else:
            print("✅ VALIDATION PASSED - Structure looks correct!\n")
            return True


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dragonfly Civil Backend Structure Refactor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.refactor_structure --dry-run
    python -m tools.refactor_structure --dry-run --verbose
    python -m tools.refactor_structure --apply
    python -m tools.refactor_structure --validate
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without executing",
    )
    group.add_argument(
        "--apply",
        action="store_true",
        help="Execute the refactoring",
    )
    group.add_argument(
        "--validate",
        action="store_true",
        help="Validate import consistency",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )

    args = parser.parse_args()

    if args.validate:
        validator = ImportValidator(PROJECT_ROOT, verbose=args.verbose)
        return 0 if validator.validate() else 1
    else:
        engine = RefactorEngine(
            PROJECT_ROOT,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
        success = engine.execute()
        return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
